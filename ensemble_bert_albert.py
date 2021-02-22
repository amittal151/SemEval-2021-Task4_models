import csv
import sys

f1 = open("Albert_test_2.csv", 'r') 
f2 = open("Bert_task1_test2.csv", 'r')
f3 = open('subtask3.csv', 'w')

reader1 = csv.reader(f1, delimiter=',')
reader2 = csv.reader(f2, delimiter=',')
header1 = next(reader1)
header2 = next(reader2)

writer = csv.writer(f3, delimiter=',')
predictions = []
albert = []
bert = []

for i, row in enumerate(reader1):
    albert.append(row)

for i, row in enumerate(reader2):
    bert.append(row)


for idx, row in enumerate(albert):
    mx = -9999.0
    pred_idx = 1
    for i in range(1, 6):
        if(mx < float(row[i]) + float(bert[idx][i])):
            pred_idx = i
            mx = float(row[i]) + float(bert[idx][i])
    
    pred_idx -= 1
    predictions.append(pred_idx)

print(predictions)


writer = csv.writer(f3, delimiter = ',')
for i, pred in enumerate(predictions):
    writer.writerow([i, pred])


# for i, row in enumerate(reader1):
#     writer.writerow([i, row[0]])