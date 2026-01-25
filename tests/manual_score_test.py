import Levenshtein

ref = "hello world"
hyp = "hello world"
ratio = Levenshtein.ratio(ref, hyp)
print(f"Match: {ref} vs {hyp} -> {ratio}")

hyp2 = "hallow world"
ratio2 = Levenshtein.ratio(ref, hyp2)
print(f"Mismatch: {ref} vs {hyp2} -> {ratio2}")
