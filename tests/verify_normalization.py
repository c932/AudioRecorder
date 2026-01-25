import string
import Levenshtein

def normalize(text):
    return text.translate(str.maketrans('', '', string.punctuation)).lower().strip()

def test_scoring(ref, rec):
    n_ref = normalize(ref)
    n_rec = normalize(rec)
    score = Levenshtein.ratio(n_ref, n_rec)
    print(f"Ref: '{ref}' -> '{n_ref}'")
    print(f"Rec: '{rec}' -> '{n_rec}'")
    print(f"Score: {score:.4f}")
    return score

print("--- Test Case 1: Punctuation Difference ---")
assert test_scoring("Hello, World!", "hello world") == 1.0

print("\n--- Test Case 2: Apostrophe Handling ---")
assert test_scoring("It's a nice day.", "its a nice day") == 1.0

print("\n--- Test Case 3: Exact Match ---")
assert test_scoring("Good morning.", "Good morning.") == 1.0

print("\n--- Test Case 4: Real Mismatch ---")
score = test_scoring("Apple", "Banana")
assert score < 0.2

print("\nAll tests passed!")
