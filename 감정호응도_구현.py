# -*- coding: utf-8 -*-
"""감정호응도_구현 (1).ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1wEmYAPzEAPoD5dzetdXrqXinIK9scnS5

## 기본 감정분류 모델 구축
"""

# Commented out IPython magic to ensure Python compatibility.
# %cd /content/drive/My Drive/Colab Notebooks/Emotion/

!ls

!pip install mxnet
!pip install gluonnlp pandas tqdm
!pip install sentencepiece
!pip install transformers==3
!pip install torch==1.12.1

!pip install git+https://git@github.com/SKTBrain/KoBERT.git@master

import torch
from torch import nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import gluonnlp as nlp
import numpy as np
from tqdm import tqdm, tqdm_notebook

from kobert.utils import get_tokenizer
from kobert.pytorch_kobert import get_pytorch_kobert_model

from transformers import AdamW
from transformers.optimization import get_cosine_schedule_with_warmup
import warnings
warnings.filterwarnings(action='ignore')

device = torch.device("cuda:0")

bertmodel, vocab = get_pytorch_kobert_model()

import pandas as pd
df = pd.read_csv('감정 분류 데이터셋.csv',encoding='cp949')
df = df.iloc[:, [1, 2]]
df2 = pd.read_excel('speech.xlsx')

df3 = df2.iloc[1:2000,[1,2]]
df3.columns=['대화', '감정']

df.loc[(df['1번 감정'] == "angry"), '1번 감정'] = 0
df.loc[(df['1번 감정'] == "anger"), '1번 감정'] = 0
df.loc[(df['1번 감정'] == "disgust"), '1번 감정'] = 0
df.loc[(df['1번 감정'] == "fear"), '1번 감정'] = 0
df.loc[(df['1번 감정'] == "sadness"), '1번 감정'] = 0
df.loc[(df['1번 감정'] == "sad"), '1번 감정'] = 0
df.loc[(df['1번 감정'] == "neutral"), '1번 감정'] = 1
df.loc[(df['1번 감정'] == "surprise"), '1번 감정'] = 1
df.loc[(df['1번 감정'] == "happiness"), '1번 감정'] = 2
df.columns=['대화', '감정']

df3.loc[(df3['감정'] == "슬픔"), '감정'] = 0
df3.loc[(df3['감정'] == "공포"), '감정'] = 0
df3.loc[(df3['감정'] == "혐오"), '감정'] = 0
df3.loc[(df3['감정'] == "분노"), '감정'] = 0
df3.loc[(df3['감정'] == "부정"), '감정'] = 0
df3.loc[(df3['감정'] == "중립"), '감정'] = 1
df3.loc[(df3['감정'] == "놀람"), '감정'] = 1
df3.loc[(df3['감정'] == "행복"), '감정'] = 2
df3.loc[(df3['감정'] == "긍정"), '감정'] = 2

df_test = pd.read_csv('emotion_labeling.csv', encoding='cp949')
df_test.loc[(df_test['감정'] == '공포'), '감정'] = 0
df_test.loc[(df_test['감정'] == '분노'), '감정'] = 0
df_test.loc[(df_test['감정'] == '슬픔'), '감정'] = 0
df_test.loc[(df_test['감정'] == '혐오'), '감정'] = 0
df_test.loc[(df_test['감정'] == '부정'), '감정'] = 0
df_test.loc[(df_test['감정'] == '놀람'), '감정'] = 1
df_test.loc[(df_test['감정'] == '중립'), '감정'] = 1
df_test.loc[(df_test['감정'] == '긍정'), '감정'] = 2

print(np.unique(df['감정']))
print(np.unique(df_test.감정))

train_df = pd.concat([df, df3])
test_df = df_test

train = []
for q, label in zip(train_df['대화'], train_df['감정'])  :
    data = []
    data.append(q)
    data.append(str(label))

    train.append(data)

test = []
for q, label in zip(test_df['대화'], test_df['감정'])  :
    data = []
    data.append(q)
    data.append(str(label))

    test.append(data)

class BERTDataset(Dataset):
    def __init__(self, dataset, sent_idx, label_idx, bert_tokenizer, max_len, pad, pair):
        transform = nlp.data.BERTSentenceTransform(bert_tokenizer, max_seq_length=max_len, pad=pad, pair=pair)
        self.sentences = [transform([i[sent_idx]]) for i in dataset]
        self.labels = [np.int32(i[label_idx]) for i in dataset]

    def __getitem__(self, i):
        return (self.sentences[i] + (self.labels[i], ))

    def __len__(self):
        return (len(self.labels))

# Setting parameters
max_len = 64
batch_size = 64
warmup_ratio = 0.1
num_epochs = 5
max_grad_norm = 1
log_interval = 200
learning_rate = 5e-5

#토큰화
tokenizer = get_tokenizer()
tok = nlp.data.BERTSPTokenizer(tokenizer, vocab, lower=False)

data_train = BERTDataset(train, 0, 1, tok, max_len, True, False)
data_test = BERTDataset(test, 0, 1, tok, max_len, True, False)

train_dataloader = torch.utils.data.DataLoader(data_train, batch_size=batch_size, num_workers=5)
test_dataloader = torch.utils.data.DataLoader(data_test, batch_size=batch_size, num_workers=5)

class BERTClassifier(nn.Module):
    def __init__(self,
                 bert,
                 hidden_size = 768,
                 num_classes = 3, # softmax 사용 <- binary일 경우는 2
                 dr_rate=None,
                 params=None):
        super(BERTClassifier, self).__init__()
        self.bert = bert
        self.dr_rate = dr_rate

        self.classifier = nn.Linear(hidden_size , num_classes)
        if dr_rate:
            self.dropout = nn.Dropout(p=dr_rate)

    def gen_attention_mask(self, token_ids, valid_length):
        attention_mask = torch.zeros_like(token_ids)
        for i, v in enumerate(valid_length):
            attention_mask[i][:v] = 1
        return attention_mask.float()

    def forward(self, token_ids, valid_length, segment_ids):
        attention_mask = self.gen_attention_mask(token_ids, valid_length)

        _, pooler = self.bert(input_ids = token_ids, token_type_ids = segment_ids.long(), attention_mask = attention_mask.float().to(token_ids.device))
        if self.dr_rate:
            out = self.dropout(pooler)
        return self.classifier(out)

model = BERTClassifier(bertmodel, dr_rate=0.5).to(device)

no_decay = ['bias', 'LayerNorm.weight']
optimizer_grouped_parameters = [
    {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
    {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
]

# 옵티마이저 선언
optimizer = AdamW(optimizer_grouped_parameters, lr=learning_rate)
loss_fn = nn.CrossEntropyLoss() # softmax용 Loss Function 정하기 <- binary classification도 해당 loss function 사용 가능

t_total = len(train_dataloader) * num_epochs
warmup_step = int(t_total * warmup_ratio)

scheduler = get_cosine_schedule_with_warmup(optimizer, num_warmup_steps=warmup_step, num_training_steps=t_total)

def calc_accuracy(X,Y):
    max_vals, max_indices = torch.max(X, 1)
    train_acc = (max_indices == Y).sum().data.cpu().numpy()/max_indices.size()[0]
    return train_acc

import torch, gc
gc.collect()
torch.cuda.empty_cache()

for e in range(num_epochs):
    train_acc = 0.0
    test_acc = 0.0

    model.train()
    for batch_id, (token_ids, valid_length, segment_ids, label) in enumerate(tqdm_notebook(train_dataloader)):
        optimizer.zero_grad()
        token_ids = token_ids.long().to(device)
        segment_ids = segment_ids.long().to(device)
        valid_length= valid_length
        label = label.long().to(device)
        out = model(token_ids, valid_length, segment_ids)
        loss = loss_fn(out, label)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm) # gradient clipping
        optimizer.step()
        scheduler.step()  # Update learning rate schedule
        train_acc += calc_accuracy(out, label)
        if batch_id % log_interval == 0:
            print("epoch {} batch id {} loss {} train acc {}".format(e+1, batch_id+1, loss.data.cpu().numpy(), train_acc / (batch_id+1)))
    print("epoch {} train acc {}".format(e+1, train_acc / (batch_id+1)))

    model.eval() # 평가 모드로 변경

    for batch_id, (token_ids, valid_length, segment_ids, label) in enumerate(tqdm_notebook(test_dataloader)):
        token_ids = token_ids.long().to(device)
        segment_ids = segment_ids.long().to(device)
        valid_length= valid_length
        label = label.long().to(device)
        out = model(token_ids, valid_length, segment_ids)
        test_acc += calc_accuracy(out, label)
    print("epoch {} test acc {}".format(e+1, test_acc / (batch_id+1)))

def classify_emotion(sentences):    # 감정 분류 함수

  unseen_values = pd.DataFrame([[sentences, 0]], columns = [['대화 내용', '감정']]).values
  test_set = BERTDataset(unseen_values, 0, 1, tok, max_len, True, False)
  test_input = torch.utils.data.DataLoader(test_set, batch_size=1, num_workers=5)

  for batch_id, (token_ids, valid_length, segment_ids, label) in enumerate(test_input):
    token_ids = token_ids.long().to(device)
    segment_ids = segment_ids.long().to(device)
    valid_length= valid_length
    out = model(token_ids, valid_length, segment_ids)
    max_vals, max_indices = torch.max(out, 1)

    temp = max_indices.data.cpu().numpy()
    if temp == [0]:
      final_value = -1
    elif temp == [1]:
      final_value = 0
    else:
      final_value = 1

  return final_value

# 예시문장
classify_emotion('생크림은 질색이야')

"""## 예시 문장"""

import time

def score_1(sentences_list): # 점수 측정 함수
    start = time.time()
    X = []
    for i in range(len(sentences_list)):

      x_1 = classify_emotion(sentences_list[i])

      if i == 0:
        x_2 = (classify_emotion(sentences_list[i]) + classify_emotion(sentences_list[i+1]))/2
      elif i == (len(sentences_list)-1):
        x_2 = (classify_emotion(sentences_list[i]) + classify_emotion(sentences_list[i-1]))/2
      else:
        x_2 = (classify_emotion(sentences_list[i]) + classify_emotion(sentences_list[i-1]) + classify_emotion(sentences_list[i+1]) )/3

      X_3 = 0
      for i in range(len(sentences_list)):
        temp = classify_emotion(sentences_list[i])
        X_3 = X_3 + temp

      x_3 = X_3 / len(sentences_list)

      x = x_1*0.4 + x_2*0.3 + x_3*0.3
      X.append(x)
      end = time.time() - start
    return(X, end)

def score_2(sentences_list): # 점수 측정 함수
    start = time.time()
    X = list(0 for i in range(len(sentences_list)))
    X_1 = list(0 for i in range(len(sentences_list)))
    X_2 = list(0 for i in range(len(sentences_list)))
    X_3 = 0

    for i in range(len(sentences_list)):
      X_1[i]= classify_emotion(sentences_list[i])
    X_3 = np.mean(X_1)
    for i in range(len(sentences_list)):
      if i == 0:
        x_2 = (X_1[i] +X_1[i+1])/2
      elif i == (len(sentences_list)-1):
        x_2 = (X_1[i] + X_1[i-1])/2
      else:
        x_2 = (X_1[i] + X_1[i-1] + X_1[i+1])/3
      X_2[i] = x_2

      X[i]= X_1[i]*0.4 + X_2[i]*0.3 + X_3*0.3
      end = time.time()
    return(X, end-start)

sent_1 = ['끝나고 디저트 카페 어때요?',
        '그럼요~ 여기 쇼트케이크 진짜 맛있어요!',
        ' 아뇨,, 뭐 그냥 크게 걱정 안해요. ㅋㅋ 먹고 싶은 거 먹는 거죠 뭐',
        ' 그래요? 싫어하는 사람도 있구나, 그럼 초콜릿은요? 초콜릿 진짜 맛있어요!']

sent_2 = ['아.. 디저트요? 좀 곤란한데요.. 좋아하시나요?',
          '하아.. 저는 디저트로 뚱뚱해지는게 싫어요.. 그런 걱정 안하시나봐요..',
          '대단하시네요. 전 생크림은 질색이에요.',
          '초콜릿도 잘 안 먹어요..ㅠㅠ']

score_1 = score_1(sent_1)
score_1

score_1 = score_2(sent_1)
score_1

score_2 = score(sent_2)
score_2

import matplotlib.pyplot as plt
plt.plot(score_1, label='Person 1')
plt.plot(score_2, color='red', label='Person 2')
plt.ylim(-1, 1)
plt.legend()
plt.show()

sent_3 = ['오늘 저녁 뭐 드셨어요?',
      '와~ 맛있으셨나요?',
      '저는 로제 떡볶이 먹어본 적 없어요.. 어떤 맛인가요?',
      '네 궁금하네요 ㅋㅋㅋ 한번 먹어봐야겠어요!',
      '전 김치찌개 먹었어요! 저는 저희 집 김치찌개가 젤 맛있는 것 같아요 ㅋㅋ',
      '저는 참치 넣는 것 좋아해요',
      '엄마표가 최고에요 진짜 ㅋㅋ']

sent_4 = ['오늘은 떡군이네 떡볶이라는 곳에서 로제 떡볶이 시켜 먹었어요.',
          '네 맛있더라고요. 한창 유행일 때는 잘 안 먹엇는데, 뒤늦게 자주 먹고 있어요.',
          '약간 떡 같은데 좀 더 쫄깃한 맛이에요. 나중에 한번 드셔보세요.',
          '꼭 배민에서 시켜 드세요. 거기꺼가 맛있어요. ㅋㅋ 혹시 저녁 뭐 드셨나요?',
          '역시 김치찌개 맛있죠! 뭐 넣어 드시는 거 좋아하세요?',
          '저희 엄마도 참치 좋아하셔서 언제나 참치 김치찌개에요.',
          '그렇죠 ㅋㅋ']

score_3 = score(sent_3)
score_3

score_4 = score(sent_4)
score_4

import matplotlib.pyplot as plt
plt.plot(score_3, label='Person 1')
plt.plot(score_4, color='red', label='Person 2')
plt.ylim(-1, 1)
plt.legend()
plt.show()

"""## 다른 유사도 측정 지표 고민"""

import numpy as np
from numpy import dot
from numpy.linalg import norm

def cos_sim(A, B):
  return dot(A, B)/(norm(A)*norm(B))

cos_sim(score_1, score_2)

cos_sim(score_3, score_4)

def euclidean(x, y):
  x = np.array(x)
  y = np.array(y)
  return np.sqrt(np.sum((x-y)**2))

euclidean(score_1, score_2)

euclidean(score_3, score_4)

def manhattan(x, y):
  x = np.array(x)
  y = np.array(y)
  return np.sum(np.abs(x-y))

manhattan(score_1, score_2)

manhattan(score_3, score_4)

"""## 실제 적용"""

df4 = pd.read_csv('df4.csv')
#df4 = df4.dropna(axis=1)
#intimacy = df4.iloc[4000:6000,-1]
df4 = df4.iloc[:115, 3:22]
df4

df4.isnull().sum()

person_1 = []
person_2 = []
for i in range(len(df4)):
  sent_person_1 = []
  sent_person_2 = []
  for i2 in range(19):
    if (i2 %2 == 0) & (str(df4.iloc[i, i2]) != 'nan'):
      sent_person_1.append(df4.iloc[i,i2])
    elif (i2 %2 ==1) & (str(df4.iloc[i, i2]) != 'nan'):
      sent_person_2.append(df4.iloc[i,i2])

  person_1.append(sent_person_1)
  person_2.append(sent_person_2)

def score_final(sentences_list): # 점수 측정 함수
    X = list(0 for i in range(len(sentences_list)))
    X_1 = list(0 for i in range(len(sentences_list)))
    X_2 = list(0 for i in range(len(sentences_list)))
    X_3 = 0

    for i in range(len(sentences_list)):
      X_1[i]= classify_emotion(sentences_list[i])
    X_3 = np.mean(X_1)
    for i in range(len(sentences_list)):
      if i == 0:
        x_2 = (X_1[i] +X_1[i+1])/2
      elif i == (len(sentences_list)-1):
        x_2 = (X_1[i] + X_1[i-1])/2
      else:
        x_2 = (X_1[i] + X_1[i-1] + X_1[i+1])/3
      X_2[i] = x_2

      X[i]= X_1[i]*0.4 + X_2[i]*0.3 + X_3*0.3

    return(X)

scores_1 = []
scores_2 = []
for i in range(len(df4)):
  scores_1.append(score_final(person_1[i]))
  scores_2.append(score_final(person_2[i]))

scores_1[0]

'''
상, 중, 중, 하, 상, 상, 중, 상,
중, 하, 상, 하, 중, 중, 하, 상,
상, 중, 상, 하, 상, 상, 상, 상,
중, 하, 중, 상, 상, 하, 중, 하,
상, 중, 상, 상, 중, 상, 중, 하
중, 중, 상, 하, 상, 중, 상, 중,
중, 중, 하, 중, 중, 상, 중, 상,
중, 상, 하, 중, 상, 상, 중, 중,
중, 상, 중, 상, 상, 중, 상, 하,
하, 상, 상, 상, 상, 상, 중, 중
상, 중, 상, 상, 중, 중, 상, 상,
상, 중, 하, 하, 중, 중, 상, 상,
하, 상, 하, 상, 중, 상, 중, 하,
상, 상, 중, 중, 상, 상, 하, 중,
중, 중, 중
'''

pip install dtaidistance

print(len(scores_2))
print(len(scores_1))

from dtaidistance import dtw

distance = []
for i in range(len(scores_1)):
  distance.append(dtw.distance(scores_1[i], scores_2[i]))

df['similarity'] = df['distance'].map(lambda x: 1-x)

manhattan_ = []
cosine = []
euclidean_ = []

for i in range(len(scores_1)):
  manhattan_.append(manhattan(scores_1[i], scores_2[i]))
  cosine.append(cos_sim(scores_1[i], scores_2[i]))
  euclidean_.append(euclidean(scores_1[i], scores_2[i]))

len(distance)

df = pd.DataFrame({'distance': distance, 'intimacy': intimacy})
df

df.to_csv('similarity_3.csv')

import pandas as pd
df = pd.read_csv('similarity.csv')
df

df['similarity'] = df['distance'].map(lambda x: 1-x)

df.sort_values('similarity').head(10)

df.sort_values('similarity').tail(10)

df.loc[df.similarity == 1.0]

df[condition]

condition = (df.similarity >= 0.4) & (df.similarity <= 0.6)



plt.hist(df.similarity)

plt.hist(df.similarity, bins=3)

df = df.iloc[:,[1,2]]



import matplotlib.pyplot as plt
plt.scatter(distance, intimacy)

df_corr = df.corr(method='pearson')
import seaborn as sns
sns.heatmap(df_corr, annot=True)

plt.plot(df.distance)

plt.hist(df.distance);

distance = df.distance.values
type(distance)

from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt
scaler = MinMaxScaler()
df.distance = scaler.fit_transform(df.distance.values.reshape(-1, 1))
plt.hist(df.distance);

plt.hist(1- df.distance, bins=3)

pd.set_option('display.max_rows', None)

df[:115]



df['distance']= df.distance

plt.hist(distance, bins=10)

plt.boxplot(df.distance)

df.describe()

import pandas as pd
df = pd.read_csv('similarity.csv')
df

df.describe()

import matplotlib.pyplot as plt
plt.hist(df.distance)

from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt
scaler = MinMaxScaler()
df.distance = scaler.fit_transform(df.distance.values.reshape(-1, 1))
plt.hist(df.distance);

plt.hist(df.similarity)

df['similarity'] = df['distance'].map(lambda x: 1-x)
df[:115]

condition = (df.similarity >=0.59) & (df.similarity <=0.80)

df[condition][:50]

상 = 1
중 = 0.5
하 = 0

scores = [상, 중, 중, 하, 상, 상, 중, 상,
중, 하, 상, 하, 중, 중, 하, 상,
상, 중, 상, 하, 상, 상, 상, 상,
중, 하, 중, 상, 상, 하, 중, 하,
상, 중, 상, 상, 중, 상, 중, 하,
중, 중, 상, 하, 상, 중, 상, 중,
중, 중, 하, 중, 중, 상, 중, 상,
중, 상, 하, 중, 상, 상, 중, 중,
중, 상, 중, 상, 상, 중, 상, 하,
하, 상, 상, 상, 상, 상, 중, 중,
상, 중, 상, 상, 중, 중, 상, 상,
상, 중, 하, 하, 중, 중, 상, 상,
하, 상, 하, 상, 중, 상, 중, 하,
상, 상, 중, 중, 상, 상, 하, 중,
중, 중, 중]

human = df.similarity[:115]

pd.concat([human, scores], axis=1)

import pickle
with open("topic_sim.pkl","rb") as fr:
    data = pickle.load(fr)
print(data)

print(data[:115])

list(data[:115])

df_topic = pd.DataFrame(data[:115])
df_topic.columns = ['topic_similarity', 'index']

# Commented out IPython magic to ensure Python compatibility.
# %ls

df

emotion_scores = pd.DataFrame(scores)

df_final = pd.concat([df_topic.topic_similarity, human, emotion_scores], axis=1)
df_final.fillna(0)
df_final.columns = ['topic', 'emotion', 'human']

import numpy as np
df_final['final_scores'] = (df_final['topic'] + df_final['emotion'])/2

df_final

human_score = [상,	상,	중,	중,	상,	상,	상,	상,
중,	하,	상,	하,	상,	중,	상,	상,
상,	중,	상,	중,	중,	상,	하,	상,
중,	하,	하,	상,	상,	하,	중,	중,
상,	상,	하,	중,	중,	상,	하,	하,
상,	하,	상,	중,	상,	하,	상,	상,
상,	중,	하,	중,	상,	상,	하,	상,
상,	중,	상,	상,	상,	상,	상,	상,
상,	중,	상,	상,	중,	상,	하,	중,
상,	상,	상,	상,	상,	상,	상,	상,
상,	상,	중,	상,	상,	상,	중,	중,
상,	하,	중,	상,	상,	상,	상,	상,
상,	상,	상,	중,	하,	상,	중,	상,
중,	하,	하,	상,	하,	중,	상,	중,
하,	상,	하]

df_final['humans'] = human_score

human_scores_2 = [중,	중,	상,	하,	중,	중,	상,	중,	하,	하,
상,	하,	중,	하,	하,	중,	상,	중,	중,	중,
중,	중,	하,	중,	중,	하,	하,	중,	중,	하,
하,	중,	중,	중,	하,	중,	중,	상,	하,	하,
중,	중,	상,	중,	중,	하,	중,	중,	하,	하,
중,	하,	중,	상,	하,	중,	중,	상,	중,	하,
중,	하,	하,	중,	상,	중,	하,	중,	중,	하,
중,	하,	하,	상,	중,	하,	중,	하,	중,	중,
중,	하,	하,	하,	중,	중,	하,	중,	하,	중,
하,	중,	중,	중,	상,	중,	중,	상,	하,	중,
중,	상,	중,	중,	중,	상,	중,	하,	중,	상,
중,	하,	중,	중,	상
]

df_final['human_2'] = human_scores_2



df_corr = df_final.corr(method='spearman')
import seaborn as sns
sns.heatmap(df_corr, annot=True)

상 = 1
중 = 0.7
하 = 0

emotion_scores = [상, 중, 중, 하, 상, 상, 중, 상, 중, 중,
상, 상, 중, 하, 상, 상, 상, 상, 상, 중,
상, 상, 중, 상, 상, 상, 상, 상, 상, 하,
중, 하, 상, 상, 상, 상, 상, 상, 중, 하,
상, 상, 상, 하, 상, 상, 상, 상, 상, 상,
상, 중, 중, 상, 중, 상, 중, 상, 상, 상,
상, 상, 하, 중, 중, 상, 중, 상, 상, 중,
상, 하, 상, 상, 상, 상, 상, 상, 중, 상,
상, 상, 상, 상, 상, 상, 상, 상, 상, 상,
상, 중, 상, 상, 상, 중, 상, 상, 중, 상,
중, 중, 중, 하, 상, 중, 상, 상, 상, 상,
하, 상, 상, 중, 중, 상]

df

from sklearn.preprocessing import MinMaxScaler
scaler = MinMaxScaler()
df.distance = scaler.fit_transform(df.distance.values.reshape(-1, 1))

df_score = df.iloc[:116,1]
df_score

len(emotion_scores)

df_emotion = pd.concat([pd.DataFrame(emotion_scores), df_score], axis=1)
df_emotion

df_corr = df_emotion.corr(method='pearson')
import seaborn as sns
sns.heatmap(df_corr, annot=True)

import pandas as pd
df1 = pd.read_csv('similarity.csv')

df2 = pd.read_csv('similarity_2.csv')

df3 = pd.read_csv('similarity_3.csv')

df = pd.concat([df1, df2, df3])
df

from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt
scaler = MinMaxScaler()
df.distance = scaler.fit_transform(df.distance.values.reshape(-1, 1))
plt.hist(df.distance);

df['similarity'] = df['distance'].map(lambda x: 1-x)
df = df.iloc[:, [0, 3]]
df.head()

df.columns = ['index', 'similarity']

df

import pickle
df.to_pickle('emotion_similarity.pkl')

data = pd.read_pickle('emotion_similarity.pkl')
data

"""## 감정호응도 최적의 가중치 찾기"""

상 = 1
중 = 0.5
하 = 0

emotion_scores = [상, 중, 중, 하, 상, 상, 중, 상, 중, 중,
상, 상, 중, 하, 상, 상, 상, 상, 상, 중,
상, 상, 중, 상, 상, 상, 상, 상, 상, 하,
중, 하, 상, 상, 상, 상, 상, 상, 중, 하,
상, 상, 상, 하, 상, 상, 상, 상, 상, 상,
상, 중, 중, 상, 중, 상, 중, 상, 상, 상,
상, 상, 하, 중, 중, 상, 중, 상, 상, 중,
상, 하, 상, 상, 상, 상, 상, 상, 중, 상,
상, 상, 상, 상, 상, 상, 상, 상, 상, 상,
상, 중, 상, 상, 상, 중, 상, 상, 중, 상,
중, 중, 중, 하, 상, 중, 상, 상, 상, 상,
하, 상, 상, 중, 중, 상 ]

import pandas as pd
df4 = pd.read_csv('df4.csv')
df4 = df4.iloc[:116, 3:27]
df4

person_1 = []
person_2 = []
for i in range(len(df4)):
  sent_person_1 = []
  sent_person_2 = []
  for i2 in range(24):
    if (i2 %2 == 0) & (str(df4.iloc[i, i2]) != 'nan'):
      sent_person_1.append(df4.iloc[i,i2])
    elif (i2 %2 ==1) & (str(df4.iloc[i, i2]) != 'nan'):
      sent_person_2.append(df4.iloc[i,i2])

  person_1.append(sent_person_1)
  person_2.append(sent_person_2)

params = [[0.1, 0.1, 0.8],
          [0.1, 0.2, 0.7],
          [0.1, 0.3, 0.6],
          [0.1, 0.4, 0.5],
          [0.1, 0.5, 0.4],
          [0.1, 0.6, 0.3],
          [0.1, 0.7, 0.2],
          [0.1, 0.8, 0.1],
          [0.2, 0.1, 0.7],
          [0.2, 0.2, 0.6],
          [0.2, 0.3, 0.5],
          [0.2, 0.4, 0.4],
          [0.2, 0.5, 0.3],
          [0.2, 0.6, 0.2],
          [0.2, 0.7, 0.1],
          [0.3, 0.1, 0.6],
          [0.3, 0.2, 0.5],
          [0.3, 0.3, 0.4],
          [0.3, 0.4, 0.3],
          [0.3, 0.5, 0.2],
          [0.3, 0.6, 0.1],
          [0.4, 0.1, 0.5],
          [0.4, 0.2, 0.4],
          [0.4, 0.3, 0.3],
          [0.4, 0.4, 0.2],
          [0.4, 0.5, 0.1],
          [0.5, 0.1, 0.4],
          [0.5, 0.2, 0.3],
          [0.5, 0.3, 0.2],
          [0.5, 0.4, 0.1],
          [0.6, 0.1, 0.3],
          [0.6, 0.2, 0.2],
          [0.6, 0.3, 0.1],
          [0.7, 0.1, 0.2],
          [0.7, 0.2, 0.1],
          [0.8, 0.1, 0.1]]

params_1 = [[0.1, 0.1, 0.8],
          [0.1, 0.2, 0.7],
          [0.1, 0.3, 0.6]]

params_2 = [[0.1, 0.4, 0.5],
          [0.1, 0.5, 0.4],
          [0.1, 0.6, 0.3]]

params_3 = [[0.1, 0.7, 0.2],
          [0.1, 0.8, 0.1],
          [0.2, 0.1, 0.7]]

params_4 = [[0.2, 0.2, 0.6],
          [0.2, 0.3, 0.5],
          [0.2, 0.4, 0.4]]

params_5 = [[0.2, 0.5, 0.3],
          [0.2, 0.6, 0.2],
          [0.2, 0.7, 0.1]]

params_6 = [[0.3, 0.1, 0.6],
          [0.3, 0.2, 0.5],
          [0.3, 0.3, 0.4]]

params_7 = [[0.3, 0.4, 0.3],
          [0.3, 0.5, 0.2],
          [0.3, 0.6, 0.1]]

params_8 = [[0.4, 0.1, 0.5],
          [0.4, 0.2, 0.4],
          [0.4, 0.3, 0.3]]

params_9 = [[0.4, 0.4, 0.2],
          [0.4, 0.5, 0.1],
          [0.5, 0.1, 0.4]]

params_10 = [[0.5, 0.2, 0.3],
          [0.5, 0.3, 0.2],
          [0.5, 0.4, 0.1]]

params_11 = [[0.6, 0.1, 0.3],
          [0.6, 0.2, 0.2],
          [0.6, 0.3, 0.1]] #채택

params_12 = [[0.7, 0.1, 0.2],
          [0.7, 0.2, 0.1],
          [0.8, 0.1, 0.1]]

def score_final(sentences_list, param): # 점수 측정 함수
    X = list(0 for i in range(len(sentences_list)))
    X_1 = list(0 for i in range(len(sentences_list)))
    X_2 = list(0 for i in range(len(sentences_list)))
    X_3 = 0

    for i in range(len(sentences_list)):
      X_1[i]= classify_emotion(sentences_list[i])
    X_3 = np.mean(X_1)
    for i in range(len(sentences_list)):
      if i == 0:
        x_2 = (X_1[i] +X_1[i+1])/2
      elif i == (len(sentences_list)-1):
        x_2 = (X_1[i] + X_1[i-1])/2
      else:
        x_2 = (X_1[i] + X_1[i-1] + X_1[i+1])/3
      X_2[i] = x_2

      X[i]= np.dot([X_1[i],X_2[i],X_3], param)

    return(X)

parameter_result_1 = []
parameter_result_2 = []

for param in params_12:
  try:
    scores_1 = []
    scores_2 = []
    for i in range(len(df4)):
      scores_1.append(score_final(person_1[i], param))
      scores_2.append(score_final(person_2[i], param))
    parameter_result_1.append(scores_1)
    parameter_result_2.append(scores_2)
  except:
    print(param, i)

len(parameter_result_1[2])

import pandas as pd
pd.DataFrame(parameter_result_1).to_csv('parameter_result_1_12.csv')
pd.DataFrame(parameter_result_2).to_csv('parameter_result_2_12.csv')

pip install dtaidistance

from dtaidistance import dtw
distances = []
for i in range(3):
  distance = []
  for j in range(len(parameter_result_1[i])):
    distance.append(dtw.distance(parameter_result_1[i][j], parameter_result_2[i][j]))

  distances.append(distance)

pd.DataFrame(distances).to_csv('distances_12.csv')

k = pd.read_csv('distances_12.csv')
k

import pandas as pd
k1 = pd.read_csv('distances_1.csv')
k2 = pd.read_csv('distances_2.csv')
k3 = pd.read_csv('distances_3.csv')
k4 = pd.read_csv('distances_4.csv')
k5 = pd.read_csv('distances_5.csv')
k6 = pd.read_csv('distances_6.csv')
k7 = pd.read_csv('distances_7.csv')
k8 = pd.read_csv('distances_8.csv')
k9 = pd.read_csv('distances_9.csv')
k10 = pd.read_csv('distances_10.csv')
k11 = pd.read_csv('distances_11.csv')
k12 = pd.read_csv('distances_12.csv')

k = pd.concat([k1, k2, k3, k4, k5, k6, k7, k8, k9, k10, k11, k12])
k = k.iloc[:, 1:]
k.reset_index(drop=True, inplace=True)
k

k = k.T
k

from sklearn.preprocessing import MinMaxScaler
scaler = MinMaxScaler()
k = scaler.fit_transform(k)
k

k = pd.DataFrame(k)

k.columns

for i in k.columns:
  k[i] = k[i].map(lambda x: 1-x)

k

len(emotion_scores)

k['emotion_scores'] = emotion_scores

k_corr = k.corr(method = 'pearson')
k_corr

k_corr.iloc[-1]

k[32]



"""## 최종 도출"""

import pandas as pd
df4 = pd.read_csv('df4.csv')
df4 = df4.iloc[6000:8000, 3:27]

person_1 = []
person_2 = []
for i in range(len(df4)):
  sent_person_1 = []
  sent_person_2 = []
  for i2 in range(24):
    if (i2 %2 == 0) & (str(df4.iloc[i, i2]) != 'nan'):
      sent_person_1.append(df4.iloc[i,i2])
    elif (i2 %2 ==1) & (str(df4.iloc[i, i2]) != 'nan'):
      sent_person_2.append(df4.iloc[i,i2])

  person_1.append(sent_person_1)
  person_2.append(sent_person_2)

def score_final(sentences_list): # 점수 측정 함수
    X = list(0 for i in range(len(sentences_list)))
    X_1 = list(0 for i in range(len(sentences_list)))
    X_2 = list(0 for i in range(len(sentences_list)))
    X_3 = 0

    for i in range(len(sentences_list)):
      X_1[i]= classify_emotion(sentences_list[i])
    X_3 = np.mean(X_1)
    for i in range(len(sentences_list)):
      if i == 0:
        x_2 = (X_1[i] +X_1[i+1])/2
      elif i == (len(sentences_list)-1):
        x_2 = (X_1[i] + X_1[i-1])/2
      else:
        x_2 = (X_1[i] + X_1[i-1] + X_1[i+1])/3
      X_2[i] = x_2

      X[i]= X_1[i]*0.6 + X_2[i]*0.3 + X_3*0.1

    return(X)

scores_1 = []
scores_2 = []
for i in range(len(df4)):
  scores_1.append(score_final(person_1[i]))
  scores_2.append(score_final(person_2[i]))

pip install dtaidistance

from dtaidistance import dtw

distance = []
for i in range(len(scores_1)):
  distance.append(dtw.distance(scores_1[i], scores_2[i]))

len(distance)

df = pd.DataFrame(distance)
df.columns = ['distance']

from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt
scaler = MinMaxScaler()
df.distance = scaler.fit_transform(df.distance.values.reshape(-1, 1))
plt.hist(df.distance);

df['similarity'] = df['distance'].map(lambda x: 1-x)

df = df.drop(columns = 'distance')
df.describe()

df

df.to_csv('final_scores_7.csv')

"""## 상, 중, 하 찾아내기"""

import pandas as pd
df1 = pd.read_csv('final_scores_1.csv')
df2 = pd.read_csv('final_scores_2.csv')
df3 = pd.read_csv('final_scores_3.csv')
df4 = pd.read_csv('final_scores_4.csv')

df = pd.concat([df1, df2, df3, df4])
df

df5 = pd.read_csv('df4.csv')
id = df5.iloc[:4000, 1]

final_df = pd.DataFrame({'index': id, 'similarity': df.similarity.values})
final_df

final_df.to_csv('similarity_4000.csv')

import matplotlib.pyplot as plt
plt.hist(final_df.similarity)

final_df.describe()

up = final_df.loc[final_df.similarity == 1.0]
#final_up = up.iloc[-100:]
#상_index = final_up['index'].values
len(up)

up[:10]

down = final_df.loc[final_df.similarity <= 0.2]
len(down)

middle = final_df.loc[(final_df.similarity <=0.51) & (final_df.similarity >=0.49)]
len(middle)

data = {
    '상': up.values,
    '중': middle.values,
    '하': down.values
}

up['range'] = '상'

middle['range'] = '중'
down['range'] = '하'

df = pd.concat([up, middle, down])
df.to_excel('range.xlsx')

pd.read_excel('range.xlsx')

import pickle
import gzip
with gzip.open('index.pickle', 'wb') as f:
    pickle.dump(data, f)

import gzip
import pickle
with gzip.open('index.pickle','rb') as f:
    data = pickle.load(f)

data

import pandas as pd
df = pd.DataFrame(data)
df.to_csv('index.csv')



import pandas as pd
df = pd.read_csv('final_scores_1.csv')
df2 = pd.read_csv('final_scores_2.csv')
df3 = pd.read_csv('final_scores_3.csv')
df4 = pd.read_csv('final_scores_4.csv')
df5 = pd.read_csv('final_scores_5.csv')
df6 = pd.read_csv('final_scores_6.csv')

df_f = pd.concat([df, df2, df3, df4, df5, df6])
df_f

df_k = pd.read_csv('df4.csv')

id = df_k['talk_id'][:6000]

df_f['id'] = id

df_f

df = df_f.iloc[:,[2,1]]

df.to_csv('final_score.csv', index=False)

"""## ANOVA 분석"""

import pandas as pd
df = pd.read_csv('final_score.csv')
df

import matplotlib.pyplot as plt
plt.hist(df.similarity)

df.id.value_counts()

con_up = (df.id=='MDRW2100016142.1') | (df.id=='MDRW2100015726.1') | (df.id=='MDRW2100015992.1') | (df.id=='MDRW2100015443.1') | (df.id=='MDRW2100015722.1')

con_mid = (df.id=='MDRW2100015526.1') | (df.id=='MDRW2100015708.1') | (df.id=='MDRW2100015429.1') | (df.id=='MDRW2100016223.1') | (df.id=='MDRW2100015744.1')

con_down = (df.id=='MDRW2100015740.1') | (df.id=='MDRW2100016220.1') | (df.id=='MDRW2100016198.1') | (df.id=='MDRW2100015980.1') | (df.id=='MDRW2100015425.1')

df.loc[con_up, 'index'] = 'up'
df.loc[con_mid, 'index'] = 'mid'
df.loc[con_down, 'index'] = 'down'

df_k = df.dropna()
df_k

up = df_k.loc[df_k['index']=='up', 'similarity']
mid = df_k.loc[df_k['index']=='mid', 'similarity']
down = df_k.loc[df_k['index']=='down', 'similarity']

import scipy.stats as stats
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm

f, p = stats.f_oneway(up, down)

p

import matplotlib.pyplot as plt
plot_data = [up, down]
ax = plt.boxplot(plot_data)
plt.show()

