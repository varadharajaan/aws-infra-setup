import names
import random
from random_word import RandomWords
from faker import Faker

# Initialize libraries
faker = Faker()
r = RandomWords()

# Filters
def is_valid(word):
    return word and word.isalpha() and 7 <= len(word) <= 9

# Generate custom professional-looking word
def generate_custom_word():
    # Try random English word first
    try:
        word = r.get_random_word()
        if is_valid(word):
            return word.lower()
    except:
        pass
    # Fallback to Faker company buzzword
    buzz = faker.catch_phrase().split()[0]
    return buzz.lower()

# Main generator
def generate_email_like_name(count=10):
    email_names = []

    for _ in range(count):
        first = names.get_first_name().lower()
        last = names.get_last_name().lower()
        suffix = generate_custom_word()
        full = f"{first}.{last}.{suffix}"
        email_names.append(full)

    return email_names

if __name__ == "__main__":
    print("📧 AI-powered Realistic Email Names:\n")
    results = generate_email_like_name(10)
    for name in results:
        print(name)
