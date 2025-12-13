#!/usr/bin/env python3
"""
EC2 Spot Instance Picker - Intelligent Low-Interruption Instance Selector (Improved)

Key upgrades:
- Configurable scoring + thresholds
- Dynamic region discovery
- AZ-aware, paginated spot price history
- Correct capacity-unit semantics for placement score
- Strict data quality gating (fail-fast by default)
- Faster instance candidate selection via Spot Advisor dataset
- Uses AWSCredentialManager ONLY (per request)
"""

import os
import sys
import json
import argparse
import requests
import boto3
import hashlib
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Any
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager
from text_symbols import Symbols

# -----------------------------
# Pretty output
# -----------------------------
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    END = '\033[0m'


# -----------------------------
# Defaults / Config
# -----------------------------
DEFAULT_INSTANCE_FAMILIES = {
    'general': ['t3', 't3a', 't4g', 'm5', 'm5a', 'm6i', 'm6a', 'm6g', 'm7i', 'm7g', 'm7a'],
    'compute': ['c5', 'c5a', 'c5n', 'c6i', 'c6a', 'c6g', 'c7i', 'c7g', 'c7a', 'c7gn'],
    'memory': ['r5', 'r5a', 'r5n', 'r6i', 'r6a', 'r6g', 'r7i', 'r7g', 'r7a', 'r7iz', 'x2idn', 'x2iedn', 'x2iezn'],
    'storage': ['i3', 'i3en', 'i4i', 'i4g', 'd2', 'd3', 'd3en', 'h1'],
    'accelerated': ['p3', 'p4', 'p5', 'g4dn', 'g5', 'g5g', 'inf1', 'inf2', 'trn1', 'trn1n']
}

DEFAULT_SCORING = {
    # points sum to 100
    "weights": {"interruption": 45, "placement": 40, "volatility": 15, "stable_bonus": 0},
    # volatility thresholds in pct (lower is better)
    "volatility_thresholds": [5, 10, 20, 30],
    # points for volatility buckets: <t1, <t2, <t3, <t4, else
    "volatility_points": [15, 12, 9, 6, 3],
    # interruption -> points mapping (AWS bands)
    "interruption_score_norm": {0: 1.0, 1: 0.8, 2: 0.6, 3: 0.4, 4: 0.2, 5: 0.0},
    # fail-fast requirements: these must be available to rank reliably
    "min_required_sources": ["advisor", "placement"],
    # if false, allow degraded ranking with warnings
    "fail_fast": True,
}

DEFAULTS = {
    "spot_advisor_url": "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json",
    "cache_ttl_hours": 24,
    "price_history_days": 7,
    "capacity_unit": "vcpu",  # "instances" or "vcpu"
    "target_capacity_vcpu": 16,
    "top_n": 20,
    "include_accelerated": False,
    "workload_type": "general",
    "vcpu_min": 2,
    "vcpu_max": 16,
    "memory_min_gb": 4.0,
    "memory_max_gb": 64.0,
    "stable_bonus_points": 0,  # intentionally default 0 (avoid misleading “known stable”)
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EC2SpotInstancePicker:
    def __init__(self, config_path: Optional[str] = None):
        self.cred_manager = AWSCredentialManager()
        self.cache_dir = os.path.join(os.getcwd(), 'aws', 'spot_cache')
        os.makedirs(self.cache_dir, exist_ok=True)

        # Load optional user config
        user_cfg: Dict[str, Any] = {}
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
            except Exception:
                user_cfg = {}

        # Merge config
        self.spot_advisor_url = user_cfg.get("spot_advisor_url", DEFAULTS["spot_advisor_url"])
        self.cache_ttl_hours = int(user_cfg.get("cache_ttl_hours", DEFAULTS["cache_ttl_hours"]))
        self.price_history_days = int(user_cfg.get("price_history_days", DEFAULTS["price_history_days"]))

        self.instance_families = user_cfg.get("instance_families", DEFAULT_INSTANCE_FAMILIES)
        self.scoring = user_cfg.get("scoring", DEFAULT_SCORING)

        stable_cfg = user_cfg.get("stable_bonus", {})
        self.stable_bonus_enabled = bool(stable_cfg.get("enabled", False))
        self.stable_bonus_points = int(stable_cfg.get("points", DEFAULTS["stable_bonus_points"]))
        self.stable_bonus_per_region = stable_cfg.get("per_region", {})  # region -> [types]

    # -----------------------------
    # Printing
    # -----------------------------
    def print_colored(self, color: str, message: str) -> None:
        print(f"{color}{message}{Colors.END}")

    def print_header(self, title: str) -> None:
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*100}")
        print(f"{title:^100}")
        print(f"{'='*100}{Colors.END}\n")

    # -----------------------------
    # Credentials & clients
    # -----------------------------
    def load_accounts(self) -> Dict[str, Dict[str, str]]:
        cfg = self.cred_manager.load_root_accounts_config()
        if not cfg or "accounts" not in cfg or not isinstance(cfg["accounts"], dict) or not cfg["accounts"]:
            raise RuntimeError("No AWS accounts configured in AWSCredentialManager config.")
        return cfg["accounts"]

    def choose_account(self, accounts: Dict[str, Dict[str, str]], preferred: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        if preferred:
            if preferred not in accounts:
                raise RuntimeError(f"Account '{preferred}' not found. Available: {', '.join(accounts.keys())}")
            return preferred, accounts[preferred]

        # Interactive choose
        names = list(accounts.keys())
        if len(names) == 1:
            return names[0], accounts[names[0]]

        self.print_colored(Colors.YELLOW, "Select AWS account:")
        for i, name in enumerate(names, 1):
            print(f"  {i}. {name}")
        choice = input(f"{Colors.BOLD}Choose [1]:{Colors.END} ").strip() or "1"
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx], accounts[names[idx]]
        except ValueError:
            pass
        self.print_colored(Colors.YELLOW, "[WARN] Invalid selection; using first account.")
        return names[0], accounts[names[0]]

    def make_session(self, account: Dict[str, str]) -> boto3.Session:
        if "access_key" not in account or "secret_key" not in account:
            raise RuntimeError("Account entry missing access_key/secret_key.")
        return boto3.Session(
            aws_access_key_id=account["access_key"],
            aws_secret_access_key=account["secret_key"],
        )

    def validate_access(self, session: boto3.Session, region: str) -> Dict[str, Any]:
        """Early validation (Feature #10)."""
        try:
            sts = session.client("sts")
            ident = sts.get_caller_identity()
        except Exception as e:
            raise RuntimeError(f"STS validation failed (bad credentials/permissions?): {e}")

        try:
            ec2 = session.client("ec2", region_name=region)
            ec2.describe_availability_zones(
                Filters=[{"Name": "region-name", "Values": [region]}]
            )
        except Exception as e:
            raise RuntimeError(f"EC2 validation failed in region '{region}' (permissions/region disabled?): {e}")

        return ident

    # -----------------------------
    # Dynamic region discovery (Feature #3)
    # -----------------------------
    def list_regions(self, session: boto3.Session, fallback: Optional[List[str]] = None) -> List[str]:
        fallback = fallback or [
            'us-east-1','us-east-2','us-west-1','us-west-2',
            'eu-west-1','eu-west-2','eu-central-1','eu-north-1',
            'ap-south-1','ap-southeast-1','ap-southeast-2','ap-northeast-1',
            'ca-central-1','sa-east-1'
        ]
        # Use a common region for describe_regions
        try:
            ec2 = session.client("ec2", region_name="us-east-1")
            resp = ec2.describe_regions(AllRegions=False)
            regions = sorted([r["RegionName"] for r in resp.get("Regions", [])])
            return regions if regions else fallback
        except Exception:
            return fallback

    # -----------------------------
    # Spot Advisor (Feature #5)
    # -----------------------------
    def get_spot_advisor_data(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Returns (data, meta)
        meta includes caching info + note about historical nature.
        """
        cache_file = os.path.join(self.cache_dir, 'spot_advisor_cache.json')
        meta: Dict[str, Any] = {
            "source": self.spot_advisor_url,
            "type": "historical_band",
            "cache_file": cache_file,
            "cached": False,
            "cache_age_hours": None,
        }

        if os.path.exists(cache_file):
            cache_age = utcnow() - datetime.fromtimestamp(os.path.getmtime(cache_file), tz=timezone.utc)
            meta["cache_age_hours"] = round(cache_age.total_seconds() / 3600, 2)
            if cache_age < timedelta(hours=self.cache_ttl_hours):
                try:
                    with open(cache_file, 'r', encoding="utf-8") as f:
                        meta["cached"] = True
                        return json.load(f), meta
                except Exception:
                    pass

        try:
            self.print_colored(Colors.YELLOW, "[FETCH] Downloading AWS Spot Instance Advisor data (historical bands)...")
            resp = requests.get(self.spot_advisor_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            with open(cache_file, 'w', encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            meta["cached"] = True
            meta["cache_age_hours"] = 0.0
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Spot Advisor data cached successfully")
            return data, meta
        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to fetch Spot Advisor data: {e}")
            return {}, meta

    def get_interruption_rate(self, instance_type: str, region: str, spot_data: Dict[str, Any]) -> Tuple[int, str]:
        """
        Returns (band_int, label)
        band_int: 0..4, 5 unknown
        """
        try:
            if 'instance_types' not in spot_data:
                return (5, "Unknown")
            it_data = spot_data['instance_types'].get(instance_type, {})
            if not it_data:
                return (5, "Unknown")
            rate_info = it_data.get('Linux', {}).get(region, {})
            rate = rate_info.get('r', 5)

            labels = {
                0: "<5% (Excellent)",
                1: "5-10% (Good)",
                2: "10-15% (Moderate)",
                3: "15-20% (High)",
                4: ">20% (Very High)",
                5: "Unknown"
            }
            return (int(rate), labels.get(int(rate), "Unknown"))
        except Exception:
            return (5, "Unknown")

    # -----------------------------
    # Placement Score (Feature #7)
    # -----------------------------



    def _placement_cache_key(self, region: str, target_capacity: int, capacity_unit: str,
                            multi_az: bool, instance_types: List[str]) -> str:
        # Stable key: sorted instance list + settings
        s = json.dumps({
            "region": region,
            "target": target_capacity,
            "unit": capacity_unit,
            "multi_az": multi_az,
            "types": sorted(instance_types),
        }, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def get_spot_placement_scores(self, ec2_client, instance_types: List[str],
                              target_capacity: int, region: str,
                              capacity_unit: str) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        Batched + cached placement score retrieval to avoid MaxConfigLimitExceeded.
        """
        if capacity_unit != "vcpu":
            raise ValueError("TargetCapacityUnitType must be 'vcpu'.")

        meta = {
            "ok": False,
            "capacity_unit": capacity_unit,
            "target_capacity": target_capacity,
            "multi_az": True,
            "cached": False,
            "cache_ttl_hours": 24,
        }

        # ---- cache (24h) ----
        cache_file = os.path.join(self.cache_dir, "placement_scores_cache.json")
        cache: Dict[str, Any] = {}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                cache = {}

        key = self._placement_cache_key(region, target_capacity, capacity_unit, True, instance_types)
        now_ts = int(utcnow().timestamp())

        if key in cache:
            entry = cache[key]
            age_hours = (now_ts - int(entry.get("ts", 0))) / 3600.0
            if age_hours <= 24 and isinstance(entry.get("scores"), dict):
                meta["cached"] = True
                meta["ok"] = any(v > 0 for v in entry["scores"].values())
                return {k: float(v) for k, v in entry["scores"].items()}, meta

        # ---- batched API calls ----
        scores: Dict[str, float] = {}
        received_any = False
        try:
            ec2_client.describe_availability_zones(Filters=[{"Name": "region-name", "Values": [region]}])

            # AWS API limit: InstanceTypes list size is constrained; use small batches
            batch_size = 10
            for i in range(0, len(instance_types), batch_size):
                batch = instance_types[i:i + batch_size]
                try:
                    resp = ec2_client.get_spot_placement_scores(
                        InstanceTypes=batch,
                        TargetCapacity=target_capacity,
                        TargetCapacityUnitType="vcpu",
                        SingleAvailabilityZone=False,
                        RegionNames=[region],
                        MaxResults=10
                    )
                    for s in resp.get("SpotPlacementScores", []):
                        it = s.get("InstanceType")
                        if it:
                            scores[it] = max(scores.get(it, 0.0), float(s.get("Score", 0.0)))
                            received_any = True
                except ClientError as e:
                    code = e.response.get("Error", {}).get("Code", "")
                    msg = e.response.get("Error", {}).get("Message", "")
                    self.print_colored(Colors.YELLOW, f"{Symbols.WARN} get_spot_placement_scores batch failed: {code} - {msg}")
                    if code == "MaxConfigLimitExceeded":
                        break

            for it in instance_types:
                if it not in scores:
                    scores[it] = 0.0

            meta["ok"] = received_any

            if meta["ok"]:
                cache[key] = {"ts": now_ts, "scores": scores}
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
                except Exception:
                    pass

            return scores, meta

        except Exception as e:
            self.print_colored(Colors.YELLOW, f"{Symbols.WARN} Placement score API unavailable: {e}")
            meta["ok"] = False
            raise

    # -----------------------------
    # Spot price history: pagination + AZ-aware (Feature #6)
    # -----------------------------
    def get_spot_price_history_az_aware(self, ec2_client, instance_types: List[str],
                                        days: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Returns (volatility_data, meta)

        volatility_data[it] = {
          "per_az": { "ap-south-1a": {avg,min,max,vol_pct,n}, ... },
          "best_az_vol_pct": float,
          "median_az_vol_pct": float,
          "avg_price": float
        }
        """
        meta = {"ok": False, "days": days, "az_aware": True, "paginated": True}
        end_time = utcnow()
        start_time = end_time - timedelta(days=days)

        try:
            paginator = ec2_client.get_paginator("describe_spot_price_history")
            page_iter = paginator.paginate(
                InstanceTypes=instance_types,
                ProductDescriptions=["Linux/UNIX"],
                StartTime=start_time,
                EndTime=end_time
            )

            prices = defaultdict(lambda: defaultdict(list))  # it -> az -> [prices]

            for page in page_iter:
                for item in page.get("SpotPriceHistory", []):
                    it = item["InstanceType"]
                    az = item.get("AvailabilityZone", "unknown")
                    try:
                        prices[it][az].append(float(item["SpotPrice"]))
                    except Exception:
                        continue

            def summarize(series: List[float]) -> Dict[str, Any]:
                if not series:
                    return {"avg": 0.0, "min": 0.0, "max": 0.0, "vol_pct": 100.0, "n": 0}
                if len(series) == 1:
                    p = series[0]
                    return {"avg": p, "min": p, "max": p, "vol_pct": 0.0, "n": 1}
                avg = sum(series) / len(series)
                mn = min(series)
                mx = max(series)
                vol = ((mx - mn) / avg * 100.0) if avg > 0 else 100.0
                return {"avg": avg, "min": mn, "max": mx, "vol_pct": vol, "n": len(series)}

            out: Dict[str, Any] = {}
            for it, az_map in prices.items():
                per_az = {az: summarize(vals) for az, vals in az_map.items()}
                vols = sorted([v["vol_pct"] for v in per_az.values() if v["n"] > 0])
                best = float(min(vols)) if vols else 100.0
                median = float(vols[len(vols)//2]) if vols else 100.0
                # average price across AZs (avg of AZ avgs)
                az_avgs = [v["avg"] for v in per_az.values() if v["n"] > 0]
                avg_price = float(sum(az_avgs) / len(az_avgs)) if az_avgs else 0.0

                out[it] = {
                    "per_az": per_az,
                    "best_az_vol_pct": round(best, 2),
                    "median_az_vol_pct": round(median, 2),
                    "avg_price": round(avg_price, 6),
                }

            meta["ok"] = bool(out)
            return out, meta
        except Exception:
            return {}, meta

    # -----------------------------
    # Instance specs
    # -----------------------------
    def get_instance_specs(self, ec2_client, instance_types: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get vCPU, memory, and other specs for instance types (resilient)."""
        specs: Dict[str, Dict[str, Any]] = {}

        # AWS API limit: 100 instance types per call
        batch_size = 100

        for i in range(0, len(instance_types), batch_size):
            batch = instance_types[i:i + batch_size]

            try:
                resp = ec2_client.describe_instance_types(InstanceTypes=batch)
                items = resp.get("InstanceTypes", [])
                for item in items:
                    it = item["InstanceType"]
                    specs[it] = {
                        "vcpus": item["VCpuInfo"]["DefaultVCpus"],
                        "memory_gb": item["MemoryInfo"]["SizeInMiB"] / 1024.0,
                        "network": item.get("NetworkInfo", {}).get("NetworkPerformance", "Unknown"),
                        "processor": (item.get("ProcessorInfo", {}).get("SupportedArchitectures", ["x86_64"]) or ["x86_64"])[0],
                        "family": it.split(".")[0],
                    }

            except ClientError as e:
                # If batch failed due to one bad instance type, fall back to per-item calls
                code = e.response.get("Error", {}).get("Code", "")
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN} describe_instance_types batch failed ({code}). Falling back to per-instance lookup...")

                for it in batch:
                    try:
                        r = ec2_client.describe_instance_types(InstanceTypes=[it])
                        items = r.get("InstanceTypes", [])
                        if not items:
                            continue
                        item = items[0]
                        specs[it] = {
                            "vcpus": item["VCpuInfo"]["DefaultVCpus"],
                            "memory_gb": item["MemoryInfo"]["SizeInMiB"] / 1024.0,
                            "network": item.get("NetworkInfo", {}).get("NetworkPerformance", "Unknown"),
                            "processor": (item.get("ProcessorInfo", {}).get("SupportedArchitectures", ["x86_64"]) or ["x86_64"])[0],
                            "family": it.split(".")[0],
                        }
                    except Exception:
                        # skip invalid/unsupported types quietly
                        continue

            except Exception as e:
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN} describe_instance_types failed for a batch: {e}")
                continue

        return specs

    def filter_to_offered_instance_types(self, ec2_client, region: str, candidates: List[str]) -> List[str]:
        offered = set()
        paginator = ec2_client.get_paginator("describe_instance_type_offerings")
        for page in paginator.paginate(
            LocationType="region",
            Filters=[{"Name": "location", "Values": [region]}]
        ):
            for o in page.get("InstanceTypeOfferings", []):
                offered.add(o["InstanceType"])
        return [it for it in candidates if it in offered]

    # -----------------------------
    # Candidate discovery (Feature #11)
    # -----------------------------
    def build_candidates(self, ec2_client, families: List[str], spot_advisor_data: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
        """
        Prefer Spot Advisor keys (fast). If unavailable, fall back to region-wide describe_instance_types paginator (slow).
        """
        meta = {"mode": "advisor_keys", "ok": False}

        # Fast path: use spot advisor keys (instance types present in dataset)
        try:
            keys = list((spot_advisor_data.get("instance_types") or {}).keys())
            if keys:
                cands = [it for it in keys if any(it.startswith(f"{fam}.") for fam in families)]
                meta["ok"] = True
                return sorted(set(cands)), meta
        except Exception:
            pass

        # Slow path fallback
        meta["mode"] = "region_scan_fallback"
        all_types: List[str] = []
        try:
            paginator = ec2_client.get_paginator("describe_instance_types")
            for page in paginator.paginate():
                all_types.extend([it["InstanceType"] for it in page.get("InstanceTypes", [])])
            cands = [it for it in all_types if any(it.startswith(f"{fam}.") for fam in families)]
            meta["ok"] = True
            return sorted(set(cands)), meta
        except Exception:
            meta["ok"] = False
            return [], meta

    # -----------------------------
    # Scoring (Feature #2 + #8)
    # -----------------------------
    def calculate_confidence(self,
                             interruption_band: int,
                             placement_score: float,
                             best_az_vol_pct: float,
                             is_stable_bonus: bool) -> Tuple[float, str, Dict[str, Any]]:
        """
        Returns (confidence_0_100, label, breakdown)
        """
        w = self.scoring["weights"]
        thresholds = self.scoring["volatility_thresholds"]
        vol_points_table = self.scoring["volatility_points"]
        intr_norm = float(self.scoring["interruption_score_norm"].get(interruption_band, 0.0))
        intr_points = intr_norm * float(w["interruption"])

        # Interruption points already scaled to w["interruption"]
        intr_points = float(intr_norm * float(w["interruption"]))

        # Placement points scaled to w["placement"]
        placement_points = (float(placement_score) / 10.0) * float(w["placement"])

        # Volatility points scaled to w["volatility"]
        # We interpret vol_points_table as already in 0..w["volatility"] scale if you set it that way.
        # Here we normalize: vol_points_table max should equal w["volatility"].
        vol_pct = float(best_az_vol_pct) if best_az_vol_pct is not None else 100.0
        if vol_pct < thresholds[0]:
            vol_points_raw = vol_points_table[0]
        elif vol_pct < thresholds[1]:
            vol_points_raw = vol_points_table[1]
        elif vol_pct < thresholds[2]:
            vol_points_raw = vol_points_table[2]
        elif vol_pct < thresholds[3]:
            vol_points_raw = vol_points_table[3]
        else:
            vol_points_raw = vol_points_table[4]

        # Scale vol_points_raw to match w["volatility"] if needed
        vol_max = max(vol_points_table) if vol_points_table else 1
        vol_points = (float(vol_points_raw) / float(vol_max)) * float(w["volatility"]) if vol_max > 0 else 0.0

        stable_points = float(self.stable_bonus_points) if (self.stable_bonus_enabled and is_stable_bonus) else 0.0
        stable_points = min(stable_points, float(w.get("stable_bonus", stable_points))) if "stable_bonus" in w else stable_points

        total = intr_points + placement_points + vol_points + stable_points
        total = max(0.0, min(100.0, total))

        if total >= 90:
            label = "Excellent (90%+)"
        elif total >= 80:
            label = "Very Good (80-89%)"
        elif total >= 70:
            label = "Good (70-79%)"
        elif total >= 60:
            label = "Moderate (60-69%)"
        else:
            label = "Low (<60%)"

        breakdown = {
            "interruption_points": round(intr_points, 2),
            "placement_points": round(placement_points, 2),
            "volatility_points": round(vol_points, 2),
            "stable_points": round(stable_points, 2),
            "best_az_vol_pct": round(vol_pct, 2),
        }
        return round(total, 1), label, breakdown

    # -----------------------------
    # Main recommendation engine
    # -----------------------------
    def get_instance_recommendations(self,
                                     session: boto3.Session,
                                     region: str,
                                     workload_type: str,
                                     vcpu_min: int,
                                     vcpu_max: int,
                                     memory_min_gb: float,
                                     memory_max_gb: float,
                                     target_capacity: int,
                                     capacity_unit: str,
                                     include_accelerated: bool,
                                     top_n: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Returns (recommendations, run_metadata)
        """
        self.print_header(f"EC2 SPOT INSTANCE PICKER - {region.upper()}")

        # Validate / create EC2 client
        ec2_client = session.client("ec2", region_name=region)

        # Step 0: Spot advisor data (historical)
        self.print_colored(Colors.CYAN, "[STEP 0] Fetching Spot Advisor (historical interruption bands)...")
        spot_advisor_data, advisor_meta = self.get_spot_advisor_data()

        # Step 1: Determine families
        self.print_colored(Colors.CYAN, f"[STEP 1] Selecting families for workload='{workload_type}'...")
        if workload_type == "mixed":
            wtypes = ["general", "compute", "memory", "storage"]
            if include_accelerated:
                wtypes.append("accelerated")
            families = sorted(set(sum([self.instance_families.get(w, []) for w in wtypes], [])))
        else:
            families = self.instance_families.get(workload_type, self.instance_families.get("general", []))

        if not families:
            families = self.instance_families.get("general", [])
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Using families: {', '.join(families)}")

        # Step 2: Build candidate instance types (fast if advisor available)
        self.print_colored(Colors.CYAN, "[STEP 2] Building candidate instance types...")
        candidates, cand_meta = self.build_candidates(ec2_client, families, spot_advisor_data)
        if not candidates:
            raise RuntimeError("No candidate instance types found (Spot Advisor missing and region scan failed).")
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Candidates: {len(candidates)} (mode={cand_meta['mode']})")

        self.print_colored(Colors.CYAN, "[STEP 2.5] Filtering candidates to instance types offered in this region...")
        candidates = self.filter_to_offered_instance_types(ec2_client, region, candidates)
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Region-offered candidates: {len(candidates)}")

        if not candidates:
            raise RuntimeError("No candidates are offered in this region after filtering.")
        # Step 3: Specs and filter
        self.print_colored(Colors.CYAN, "[STEP 3] Loading instance specs and filtering by vCPU/RAM...")
        specs = self.get_instance_specs(ec2_client, candidates)
        if not specs:
            raise RuntimeError("Failed to load instance specs (describe_instance_types returned no data).")

        filtered = []
        for it, sp in specs.items():
            if vcpu_min <= sp["vcpus"] <= vcpu_max and memory_min_gb <= sp["memory_gb"] <= memory_max_gb:
                filtered.append(it)

        self.print_colored(Colors.GREEN, f"{Symbols.OK} Filtered: {len(filtered)} match vCPU={vcpu_min}-{vcpu_max}, RAM={memory_min_gb}-{memory_max_gb} GB")
        if not filtered:
            raise RuntimeError("No instances match your vCPU/memory requirements.")

        # Step 4: Placement score
        self.print_colored(Colors.CYAN, "[STEP 4] Fetching Spot Placement Scores (AWS confidence)...")
        placement_scores, placement_meta = self.get_spot_placement_scores(
            ec2_client, filtered, target_capacity, region, capacity_unit
        )

        # Step 5: Spot price volatility (AZ-aware, paginated)
        self.print_colored(Colors.CYAN, f"[STEP 5] Analyzing Spot Price History ({self.price_history_days} days, AZ-aware)...")
        price_data, price_meta = self.get_spot_price_history_az_aware(
            ec2_client, filtered, days=self.price_history_days
        )

        # Step 6: Data quality gating (fail-fast)
        quality_overall = {
            "advisor": bool(spot_advisor_data) and "instance_types" in spot_advisor_data,
            "placement": bool(placement_meta.get("ok", False)),
            "price": bool(price_meta.get("ok", False)),
        }

        missing_required = [src for src in self.scoring.get("min_required_sources", []) if not quality_overall.get(src, False)]
        if missing_required:
            msg = f"Missing required data sources: {', '.join(missing_required)}. Results would be unreliable."
            if self.scoring.get("fail_fast", True):
                raise RuntimeError(msg)
            self.print_colored(Colors.YELLOW, f"{Symbols.WARN} {msg} Proceeding in degraded mode.")

        # Step 7: Score & rank
        self.print_colored(Colors.CYAN, "[STEP 6] Scoring and ranking...")
        recs: List[Dict[str, Any]] = []

        # Stable bonus set (optional)
        region_stable_list = set(self.stable_bonus_per_region.get(region, [])) if self.stable_bonus_enabled else set()

        for it in filtered:
            interruption_band, interruption_label = self.get_interruption_rate(it, region, spot_advisor_data)
            placement = float(placement_scores.get(it, 0.0))

            price_info = price_data.get(it, {})
            best_vol = float(price_info.get("best_az_vol_pct", 100.0))
            avg_price = float(price_info.get("avg_price", 0.0))
            median_vol = float(price_info.get("median_az_vol_pct", 100.0))

            # data-quality flags per instance
            dq = {
                "advisor": "ok" if quality_overall["advisor"] and interruption_band != 5 else "missing",
                "placement": "ok" if placement > 0 else "missing",
                "price": "ok" if it in price_data else "missing"
            }

            is_stable_bonus = it in region_stable_list
            confidence, label, breakdown = self.calculate_confidence(
                interruption_band=interruption_band,
                placement_score=placement,
                best_az_vol_pct=best_vol,
                is_stable_bonus=is_stable_bonus
            )

            sp = specs[it]
            recs.append({
                "instance_type": it,
                "confidence_score": confidence,
                "confidence_label": label,
                "vcpus": sp["vcpus"],
                "memory_gb": round(sp["memory_gb"], 1),
                "family": sp["family"],
                "processor": sp["processor"],
                "network": sp["network"],
                "interruption_band": interruption_band,
                "interruption_label": interruption_label,
                "placement_score": round(placement, 1),
                "avg_spot_price": round(avg_price, 6),
                "best_az_volatility_pct": round(best_vol, 2),
                "median_az_volatility_pct": round(median_vol, 2),
                "stable_bonus_applied": bool(is_stable_bonus),
                "data_quality": dq,
                "score_breakdown": breakdown,
            })

        # Sort: confidence desc, price asc (tie-breaker)
        recs.sort(key=lambda x: (-x["confidence_score"], x["avg_spot_price"]))

        run_meta = {
            "region": region,
            "workload_type": workload_type,
            "families_used": families,
            "filters": {"vcpu_min": vcpu_min, "vcpu_max": vcpu_max, "memory_min_gb": memory_min_gb, "memory_max_gb": memory_max_gb},
            "placement": placement_meta,
            "price_history": price_meta,
            "spot_advisor": advisor_meta,
            "candidate_discovery": cand_meta,
            "data_quality_overall": quality_overall,
            "generated_at": utcnow().isoformat()
        }

        unique_recs: List[Dict[str, Any]] = []
        seen_types = set()
        for rec in recs:
            if rec["instance_type"] in seen_types:
                continue
            seen_types.add(rec["instance_type"])
            unique_recs.append(rec)

        return unique_recs[:top_n], run_meta

    # -----------------------------
    # Output helpers
    # -----------------------------
    def export_to_json(self, recommendations: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
        out_dir = os.path.join(os.getcwd(), "aws", "spot_recommendations")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        region = meta.get("region", "unknown")
        out_file = os.path.join(out_dir, f"spot_recommendations_{region}_{ts}.json")

        payload = {"metadata": meta, "recommendations": recommendations}
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        self.print_colored(Colors.GREEN, f"[EXPORT] Saved: {out_file}")
        return out_file

    def _get_family_type(self, family: str) -> str:
        for ftype, families in self.instance_families.items():
            if family in families:
                return ftype.capitalize()
        return "Other"

    def print_simple_results(self, recommendations: List[Dict[str, Any]], region: str) -> None:
        if not recommendations:
            self.print_colored(Colors.RED, "[ERROR] No recommendations available")
            return

        print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*100}")
        print(f"SPOT INSTANCE RECOMMENDATIONS - {region.upper()}")
        print(f"{'='*100}{Colors.END}\n")

        print(f"{Colors.BOLD}{'Rank':<6} {'Instance Type':<18} {'Family':<10} {'Confidence':<12} {'Cost/Hour':<12} {'vCPU':<6} {'RAM(GB)':<8} {'DQ':<12}{Colors.END}")
        print(f"{'-'*110}")

        for idx, rec in enumerate(recommendations, 1):
            if rec["confidence_score"] >= 90:
                color, tag = Colors.GREEN, "EXCELLENT"
            elif rec["confidence_score"] >= 80:
                color, tag = Colors.CYAN, "GOOD"
            elif rec["confidence_score"] >= 70:
                color, tag = Colors.YELLOW, "MODERATE"
            else:
                color, tag = Colors.RED, "LOW"

            family_type = self._get_family_type(rec["family"])
            dq = rec.get("data_quality", {})
            dq_short = "".join([
                "A" if dq.get("advisor") == "ok" else "-",
                "P" if dq.get("placement") == "ok" else "-",
                "R" if dq.get("price") == "ok" else "-",
            ])  # Advisor/Placement/pRice

            print(
                f"{color}{tag:<9} #{idx:<3} {rec['instance_type']:<18} "
                f"{family_type:<10} {rec['confidence_score']:>6.1f}%    "
                f"${rec['avg_spot_price']:<11.6f} {rec['vcpus']:<6} {rec['memory_gb']:<8.1f} "
                f"{dq_short:<12}{Colors.END}"
            )

        print(f"{'-'*110}")

        high_conf = len([r for r in recommendations if r["confidence_score"] >= 80])
        families = len(set([r["family"] for r in recommendations]))
        avg_price = sum([r["avg_spot_price"] for r in recommendations]) / len(recommendations)

        print(f"\n{Colors.BOLD}Summary:{Colors.END}")
        print(f"  • Total Instances: {len(recommendations)}")
        print(f"  • High Confidence (≥80%): {Colors.GREEN}{high_conf}{Colors.END}")
        print(f"  • Instance Families: {families}")
        print(f"  • Average Price: ${avg_price:.6f}/hr")

    # -----------------------------
    # Interactive picker
    # -----------------------------
    def interactive_picker(self, account_name: Optional[str] = None) -> None:
        self.print_header("EC2 SPOT INSTANCE PICKER - Interactive")

        accounts = self.load_accounts()
        acct_name, acct = self.choose_account(accounts, preferred=account_name)
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Using account: {acct_name}")
        session = self.make_session(acct)

        regions = self.list_regions(session)
        self.print_colored(Colors.YELLOW, "Select AWS Region:")
        for i, r in enumerate(regions, 1):
            print(f"  {i}. {r}")

        region_choice = input(f"\n{Colors.BOLD}Choose region [1]:{Colors.END} ").strip() or "1"
        try:
            idx = int(region_choice) - 1
            region = regions[idx] if 0 <= idx < len(regions) else regions[0]
        except ValueError:
            region = regions[0]

        # Validate early
        ident = self.validate_access(session, region)
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Identity: {ident.get('Arn', '')}")

        print(f"\n{Colors.YELLOW}Workload type:{Colors.END}")
        print(f"  0. Mixed (best of multiple families)")
        print(f"  1. General")
        print(f"  2. Compute")
        print(f"  3. Memory")
        print(f"  4. Storage")
        print(f"  5. Accelerated (GPU/Infer/Train)")

        w_choice = input(f"\n{Colors.BOLD}Choose [0]:{Colors.END} ").strip() or "0"
        workload_map = {"0": "mixed", "1": "general", "2": "compute", "3": "memory", "4": "storage", "5": "accelerated"}
        workload_type = workload_map.get(w_choice, "mixed")

        include_acc = False
        if workload_type == "mixed":
            inc = input(f"{Colors.BOLD}Include accelerated families in mixed? [y/N]:{Colors.END} ").strip().lower()
            include_acc = (inc == "y")

        # Capacity semantics
        self.print_colored(Colors.YELLOW, "\nPlacement Score uses vCPU target capacity (AWS does NOT accept 'instances' here).")
        target_vcpu = input(f"{Colors.BOLD}Target capacity in vCPU (default {DEFAULTS['target_capacity_vcpu']}):{Colors.END} ").strip() or str(DEFAULTS["target_capacity_vcpu"])
        try:
            target_capacity_vcpu = max(1, int(target_vcpu))
        except ValueError:
            target_capacity_vcpu = DEFAULTS["target_capacity_vcpu"]

        cap_unit = "vcpu"

        # Run
        recs, meta = self.get_instance_recommendations(
            session=session,
            region=region,
            workload_type=workload_type,
            vcpu_min=DEFAULTS["vcpu_min"],
            vcpu_max=DEFAULTS["vcpu_max"],
            memory_min_gb=DEFAULTS["memory_min_gb"],
            memory_max_gb=DEFAULTS["memory_max_gb"],
            target_capacity=target_capacity_vcpu,
            capacity_unit=cap_unit,
            include_accelerated=include_acc,
            top_n=DEFAULTS["top_n"]
        )

        self.print_simple_results(recs, region)
        self.export_to_json(recs, meta)


# -----------------------------
# CLI
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="EC2 Spot Instance Picker (Improved, AWScred-manager only)")
    p.add_argument("--config", default=None, help="Optional JSON config file (scoring/families/cache)")
    p.add_argument("--account", default=None, help="AWS account name from AWSCredentialManager config")
    p.add_argument("--region", default=None, help="AWS region (if omitted: interactive choose)")
    p.add_argument("--workload", default="mixed", choices=["mixed","general","compute","memory","storage","accelerated"])
    p.add_argument("--include-accelerated", action="store_true", help="Include accelerated families in mixed mode")
    p.add_argument("--vcpu-min", type=int, default=DEFAULTS["vcpu_min"])
    p.add_argument("--vcpu-max", type=int, default=DEFAULTS["vcpu_max"])
    p.add_argument("--mem-min", type=float, default=DEFAULTS["memory_min_gb"])
    p.add_argument("--mem-max", type=float, default=DEFAULTS["memory_max_gb"])
    p.add_argument("--top-n", type=int, default=DEFAULTS["top_n"])
    p.add_argument("--target-capacity-vcpu", type=int, default=DEFAULTS["target_capacity_vcpu"],
               help="Target capacity in vCPU for Spot Placement Score (TargetCapacityUnitType=vcpu)")
    p.add_argument("--no-fail-fast", action="store_true", help="Allow degraded ranking if key data sources missing")
    p.add_argument("--no-export", action="store_true", help="Do not export JSON")
    p.add_argument("--non-interactive", action="store_true", help="Require region provided; no prompts")
    return p.parse_args()


def main():
    args = parse_args()
    picker = EC2SpotInstancePicker(config_path=args.config)

    # Override fail-fast if requested
    if args.no_fail_fast:
        picker.scoring["fail_fast"] = False

    # Interactive if no region or not non-interactive
    if not args.region and not args.non_interactive:
        try:
            picker.interactive_picker(account_name=args.account)
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}{Symbols.WARN} Cancelled by user{Colors.END}")
        return

    # Non-interactive path
    if not args.region and args.non_interactive:
        raise SystemExit("ERROR: --region is required with --non-interactive")

    accounts = picker.load_accounts()
    acct_name, acct = picker.choose_account(accounts, preferred=args.account)
    picker.print_colored(Colors.GREEN, f"{Symbols.OK} Using account: {acct_name}")

    session = picker.make_session(acct)
    ident = picker.validate_access(session, args.region)
    picker.print_colored(Colors.GREEN, f"{Symbols.OK} Identity: {ident.get('Arn', '')}")

    recs, meta = picker.get_instance_recommendations(
        session=session,
        region=args.region,
        workload_type=args.workload,
        vcpu_min=args.vcpu_min,
        vcpu_max=args.vcpu_max,
        memory_min_gb=args.mem_min,
        memory_max_gb=args.mem_max,
        target_capacity=max(1, args.target_capacity_vcpu),
        capacity_unit="vcpu",
        include_accelerated=args.include_accelerated,
        top_n=max(1, args.top_n),
    )

    picker.print_simple_results(recs, args.region)
    if not args.no_export:
        picker.export_to_json(recs, meta)


if __name__ == "__main__":
    main()
