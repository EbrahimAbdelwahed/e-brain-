from pipeline.cluster import hamming64
import hashlib

def shingles(text, k=1):
    words = [w for w in text.lower().split() if w]
    if len(words) <= k:
        return [" ".join(words)] if words else []
    return [" ".join(words[i:i+k]) for i in range(len(words)-k+1)]

def simhash64(text, k=1):
    bits=[0]*64
    for sh in shingles(text,k):
        h = int.from_bytes(hashlib.md5(sh.encode('utf-8')).digest()[:8], 'big')
        for i in range(64):
            bits[i] += 1 if ((h>>i)&1) else -1
    out=0
    for i,b in enumerate(bits):
        if b>0:
            out |= 1<<i
    return out

text1 = "Neural network achieves new accuracy on benchmark using simple method."
text2 = "A simple method lets a neural network hit new accuracy on the benchmark."
for k in (1,2,3,4):
    d = hamming64(simhash64(text1,k), simhash64(text2,k))
    print('k',k,'hamming',d)
