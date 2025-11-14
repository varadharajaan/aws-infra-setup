import json
import subprocess


def load_config(path="aws_accounts_config.json"):
    with open(path, "r") as f:
        return json.load(f)


def prompt_account_selection(accounts):
    print("\n📦 Available Accounts:")
    indexed_map = {}
    for i, acc in enumerate(accounts.keys(), start=1):
        print(f"  {i}. {acc}")
        indexed_map[str(i)] = acc

    selection = (
        input("\n👉 Enter account(s) to configure [comma, range, or 'all']: ")
        .strip()
        .lower()
    )

    if selection == "all":
        return list(accounts.keys())

    selected = set()

    if "," in selection:
        parts = [s.strip() for s in selection.split(",")]
    elif "-" in selection:
        parts = []
        try:
            start, end = map(int, selection.split("-"))
            parts = [str(i) for i in range(start, end + 1)]
        except ValueError:
            return []
    else:
        parts = [selection]

    for part in parts:
        if part in indexed_map:
            selected.add(indexed_map[part])

    return list(selected)


def set_aws_profile(
    profile, access_key, secret_key, region="us-east-1", output_format="json"
):
    subprocess.run(
        [
            "aws",
            "configure",
            "--profile",
            profile,
            "set",
            "aws_access_key_id",
            access_key,
        ]
    )
    subprocess.run(
        [
            "aws",
            "configure",
            "--profile",
            profile,
            "set",
            "aws_secret_access_key",
            secret_key,
        ]
    )
    subprocess.run(["aws", "configure", "--profile", profile, "set", "region", region])
    subprocess.run(
        ["aws", "configure", "--profile", profile, "set", "output", output_format]
    )
    print(f"✅ Profile configured: {profile}")


def configure_selected_accounts(accounts_data, selected_accounts, region="us-east-1"):
    print("\n🔧 Setting AWS CLI Profiles...\n")

    for acc in selected_accounts:
        data = accounts_data[acc]

        main_profile = acc
        backup_profile = f"{acc}-bk"

        set_aws_profile(
            profile=main_profile,
            access_key=data["access_key"],
            secret_key=data["secret_key"],
            region=region,
        )

        set_aws_profile(
            profile=backup_profile,
            access_key=data["backup_access_key"],
            secret_key=data["backup_secret_key"],
            region=region,
        )

    print("\n🎉 All selected profiles are now configured.")


if __name__ == "__main__":
    config = load_config()
    all_accounts = config.get("accounts", {})
    selected = prompt_account_selection(all_accounts)

    if not selected:
        print("❌ No valid accounts selected.")
    else:
        configure_selected_accounts(all_accounts, selected)
