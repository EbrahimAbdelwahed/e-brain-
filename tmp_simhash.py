from pipeline.cluster import simhash64, hamming64
text1 = "Neural network achieves new accuracy on benchmark using simple method."
text2 = "A simple method lets a neural network hit new accuracy on the benchmark."
print(bin(simhash64(text1)))
print(bin(simhash64(text2)))
print('hamming', hamming64(simhash64(text1), simhash64(text2)))
