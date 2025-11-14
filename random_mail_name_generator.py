import random
import time

import names
import requests
from faker import Faker
from random_word import RandomWords

# Initialize libraries
faker = Faker()
r = RandomWords()


class DynamicNameGenerator:
    def __init__(self):
        self.brand_names = []
        self.tech_keywords = []
        self.fallback_brands = ["microsoft", "google", "amazon", "apple", "github"]
        self.fallback_tech = ["dev", "cloud", "api", "devops", "studio"]

    def fetch_companies_from_api(self):
        """Fetch company names from public APIs"""
        try:
            # GitHub API for popular repositories (tech companies)
            github_url = "https://api.github.com/search/repositories"
            params = {
                "q": "language:python stars:>10000",
                "sort": "stars",
                "per_page": 50,
            }

            response = requests.get(github_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for repo in data.get("items", []):
                    owner = repo.get("owner", {}).get("login", "").lower()
                    # Enforce minimum 4 characters for brand names
                    if owner and len(owner) >= 4 and owner.isalpha():
                        self.brand_names.append(owner)

            print(f"✅ Fetched {len(self.brand_names)} brand names from GitHub API")

        except Exception as e:
            print(f"⚠️ GitHub API failed: {e}")

        # Try alternative APIs
        try:
            # Cryptocurrency API for tech-related names
            crypto_url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 50,
                "page": 1,
            }

            response = requests.get(crypto_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for coin in data:
                    symbol = coin.get("symbol", "").lower()
                    name = (
                        coin.get("name", "").lower().replace(" ", "").replace("-", "")
                    )

                    # Only add symbols that are 4+ characters and alphabetic
                    if symbol and len(symbol) >= 4 and symbol.isalpha():
                        self.tech_keywords.append(symbol)
                    # Only add names that are 4+ characters and alphabetic
                    if name and len(name) >= 4 and name.isalpha():
                        self.brand_names.append(name)

            print(f"✅ Fetched crypto names from CoinGecko API")

        except Exception as e:
            print(f"⚠️ CoinGecko API failed: {e}")

    def fetch_tech_keywords_from_api(self):
        """Fetch tech keywords from programming APIs"""
        try:
            # GitHub trending repositories for tech keywords
            github_url = "https://api.github.com/search/repositories"
            languages = ["python", "javascript", "java", "go", "rust", "typescript"]

            for lang in languages:
                params = {
                    "q": f"language:{lang} created:>2020-01-01",
                    "sort": "stars",
                    "per_page": 20,
                }

                response = requests.get(github_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for repo in data.get("items", []):
                        name = repo.get("name", "").lower()
                        # Enforce minimum 4 characters and alphabetic only
                        if name and 4 <= len(name) <= 12 and name.isalpha():
                            self.tech_keywords.append(name)

                time.sleep(0.5)  # Rate limiting

            print(f"✅ Fetched {len(self.tech_keywords)} tech keywords from GitHub")

        except Exception as e:
            print(f"⚠️ GitHub tech keywords API failed: {e}")

        # Try Stack Overflow API for popular tags
        try:
            so_url = "https://api.stackexchange.com/2.3/tags"
            params = {
                "order": "desc",
                "sort": "popular",
                "site": "stackoverflow",
                "pagesize": 100,
            }

            response = requests.get(so_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for tag in data.get("items", []):
                    name = tag.get("name", "").lower()
                    # Enforce minimum 4 characters and alphabetic only
                    if name and 4 <= len(name) <= 12 and name.isalpha():
                        self.tech_keywords.append(name)

            print(f"✅ Fetched tech tags from Stack Overflow API")

        except Exception as e:
            print(f"⚠️ Stack Overflow API failed: {e}")

    def load_api_data(self):
        """Load data from all APIs"""
        print("🔄 Fetching data from public APIs...")

        self.fetch_companies_from_api()
        self.fetch_tech_keywords_from_api()

        # Remove duplicates and apply strict validation
        self.brand_names = list(
            set(
                [
                    name
                    for name in self.brand_names
                    if name.isalpha() and 4 <= len(name) <= 15
                ]
            )
        )

        self.tech_keywords = list(
            set(
                [
                    name
                    for name in self.tech_keywords
                    if name.isalpha() and 4 <= len(name) <= 15
                ]
            )
        )

        # Use fallbacks if APIs failed
        if not self.brand_names:
            self.brand_names = self.fallback_brands
            print("⚠️ Using fallback brand names")

        if not self.tech_keywords:
            self.tech_keywords = self.fallback_tech
            print("⚠️ Using fallback tech keywords")

        print(f"📊 Total brands: {len(self.brand_names)}")
        print(f"📊 Total tech keywords: {len(self.tech_keywords)}")

    def is_valid(self, word):
        return word and word.isalpha() and 4 <= len(word) <= 12

    def generate_custom_word(self):
        """Generate custom word with API data"""
        # 70% chance to use API data, 30% random word
        if random.random() < 0.7 and (self.brand_names or self.tech_keywords):
            all_words = self.brand_names + self.tech_keywords
            return random.choice(all_words)
        else:
            try:
                word = r.get_random_word()
                if self.is_valid(word):
                    return word.lower()
            except:
                pass

            # Enhanced fallback with tech-like words
            fallback_words = [
                "python",
                "django",
                "flask",
                "react",
                "angular",
                "nodejs",
                "docker",
                "kubernetes",
                "github",
                "gitlab",
                "jenkins",
                "terraform",
            ]
            return random.choice(fallback_words)

    def generate_email_like_name(self, count=10):
        """Generate email-like names with API data - ALWAYS 3 parts: firstname.lastname.brand_randomword"""
        email_names = []

        for _ in range(count):
            first = names.get_first_name().lower()
            last = names.get_last_name().lower()

            # Always use firstname.lastname.brand_randomword pattern
            # Get third word from brands or tech keywords
            if self.brand_names or self.tech_keywords:
                all_words = self.brand_names + self.tech_keywords
                third_word = random.choice(all_words)
            else:
                third_word = self.generate_custom_word()

            # Always format as firstname.lastname.brand_randomword
            full = f"{first}.{last}.{third_word}"
            email_names.append(full)

        return email_names


if __name__ == "__main__":
    print("🚀 Dynamic API-Powered Email Name Generator\n")

    generator = DynamicNameGenerator()
    generator.load_api_data()

    print("\n📧 Generated Email Names (Always 3 Parts):\n")
    results = generator.generate_email_like_name(10)
    for i, name in enumerate(results, 1):
        print(f"{i:2d}. {name}")
