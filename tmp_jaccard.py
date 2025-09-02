import re
text1 = "Neural network achieves new accuracy on benchmark using simple method."
text2 = "A simple method lets a neural network hit new accuracy on the benchmark."
ws1=set(re.findall(r"\w+", text1.lower()))
ws2=set(re.findall(r"\w+", text2.lower()))
inter=len(ws1 & ws2)
union=len(ws1 | ws2)
print('sets', ws1, ws2)
print('jaccard', inter/union)
