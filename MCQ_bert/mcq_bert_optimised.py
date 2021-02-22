# -*- coding: utf-8 -*-
"""MCQ_Bert.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1R9AhqUcfEaPltmyhK5-0RxHMXIAwKS5i
"""

import logging
import os
import argparse
import random
from tqdm import tqdm, trange
import csv

import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader, RandomSampler, SequentialSampler
from torch.utils.data.distributed import DistributedSampler

from pytorch_pretrained_bert.tokenization import BertTokenizer
from pytorch_pretrained_bert.modeling import BertForMultipleChoice
from pytorch_pretrained_bert.optimization import BertAdam
from pytorch_pretrained_bert.file_utils import PYTORCH_PRETRAINED_BERT_CACHE

# Logger 
logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                    datefmt = '%m/%d/%Y %H:%M:%S',
                    level = logging.INFO)
logger = logging.getLogger(__name__)

""" Arguments
"""
# Note : Currently training model on small dataset i.e 500 train examples 
do_train = True
output_dir = None
max_seq_length = 320      # default
do_lower_case = False 
train_batch_size = 16
eval_batch_size = 8       
learning_rate = 5e-5      
num_train_epochs = 2      # Epochs - less epochs to be used for BERT
warmup_proportion = 0.1   # How to use?
seed = 42                 # Random seed
local_rank = -1
optimize_on_cpu = True   # Whether to perform optimization and keep the optimizer averages on CPU
fp16 = True              # Whether to use 16-bit float precision instead of 32-bit
loss_scale = 128          # Loss scaling, positive power of 2 values can improve fp16 convergence
gradient_accumulation_steps = 4 

# Files : 
data_dir_1 = '/content/drive/My Drive/CS779_shared_dataset/Task1/'
data_dir_2 = '/content/drive/My Drive/CS779_shared_dataset/Task2/'
train_file_1 = 'Task1_train.csv'
dev_file_1 = 'Task1_dev.csv'
train_file_2 = 'Task2_train.csv'
dev_file_2 = 'Task2_dev.csv'



"""Now we have to prepare training examples to fine-tune BertForMultipleChoice Model. 

1) First Read the Examples from the csv file.

2) Convert the words into feature vectors by using the BERT Tokenizer

-----------------------Part 1 ------------------------------
"""

def read_examples(input_file, is_train):
# Note : Currently training model on small dataset i.e 500 train examples 

    with open(input_file, 'r') as f:
        reader = csv.reader(f)
        lines = list(reader)
        if is_train :
            lines = lines[:100]
        else :
            lines = lines[:20]

    examples = [
        {
            "article" : line[0],
            "question" : line[1],

            "options" : [line[2], line[3], line[4], line[5], line[6]],
         
            "label" : int(line[7]) 
         } for line in lines[1:]    # we skip the line with the column names
    ]
    # print(examples[0])
    return examples

# examples = read_examples(input_dir + train_file)

"""----------------------Part 2-------------------------

  Convert tokens to feature vectors
"""

import sys
import matplotlib.pyplot as plt

class InputFeatures(object):
    def __init__(self, choices_features, label ):
        # We didn't stored tokens in features
        self.choices_features = [
            {
                'input_ids': input_ids,
                'input_mask': input_mask,
                'segment_ids': segment_ids
            }
            for _, input_ids, input_mask, segment_ids in choices_features 

        ]
        self.label = label


def _truncate_seq_pair(tokens_a, tokens_b, max_length):
    """Truncates a sequence pair in place to the maximum length."""
    """Need to check whether truncation really helps, coz it might remove context! :( """

    # This is a simple heuristic which will always truncate the longer sequence
    # one token at a time. This makes more sense than truncating an equal percent
    # of tokens from each, since if one sequence is very short then each token
    # that's truncated likely contains more information than a longer sequence.
    while True:
        total_length = len(tokens_a) + len(tokens_b)
        if total_length <= max_length:
            break
        if len(tokens_a) > len(tokens_b):
            tokens_a.pop()
        else:
            tokens_b.pop()


def convert_examples_to_features(examples, tokenizer, max_seq_length):
    """Loads a data file into a list of `InputBatch`s."""
    
    # Each choice will correspond to a sample on which we run the
    # inference. For a given example, we will create the 5
    # following inputs:
    # - [CLS] article [SEP] question choice_1 [SEP]
    # - [CLS] article [SEP] question choice_2 [SEP]
    # - [CLS] article [SEP] question choice_3 [SEP]
    # - [CLS] article [SEP] question choice_4 [SEP]
    # - [CLS] article [SEP] question choice_5 [SEP]
    # The model will output a single value for each input. To get the
    # final decision of the model, we will run a softmax over these 5
    # outputs.
    features = []
    num_tokens_article = []
    count = 0

    for example_index, example in enumerate(examples):
        article_tokens = tokenizer.tokenize(example['article'])
        ques_tokens = tokenizer.tokenize(example['question'])

        # num_tokens_article.append(len(article_tokens) + len(ques_tokens) )   
        # if(num_tokens_article[example_index] > 450):
        #     count += 1

        choices_features = []
        for option_index, option in enumerate(example['options']):
            # We create a copy of the article tokens in order to be
            # able to shrink it according to option_tokens
            article_tokens_option = article_tokens[:]
            q_tokens = ques_tokens + tokenizer.tokenize(option)       # Might also try replacing "@placeholder" with option
            
            # Modifies `context_tokens_choice` and `ending_tokens` in
            # place so that the total length is less than the
            # specified length.  Account for [CLS], [SEP], [SEP] with
            # "- 3"
            _truncate_seq_pair(article_tokens_option, q_tokens, max_seq_length - 3)

            tokens = ["[CLS]"] + article_tokens_option + ["[SEP]"] + q_tokens + ["[SEP]"]
            segment_ids = [0] * (len(article_tokens_option) + 2) + [1] * (len(q_tokens) + 1)

            input_ids = tokenizer.convert_tokens_to_ids(tokens)
            input_mask = [1] * len(input_ids)

            # Zero-pad up to the sequence length.
            padding = [0] * (max_seq_length - len(input_ids))
            input_ids += padding
            input_mask += padding
            segment_ids += padding

            assert len(input_ids) == max_seq_length
            assert len(input_mask) == max_seq_length
            assert len(segment_ids) == max_seq_length

            choices_features.append((tokens, input_ids, input_mask, segment_ids))

        label = example['label']
        if example_index < 5:
            logger.info("*** Example ***")
            # logger.info(f"swag_id: {example.swag_id}")
            for choice_idx, (tokens, input_ids, input_mask, segment_ids) in enumerate(choices_features):
                logger.info(f"choice: {choice_idx}")
                logger.info(f"tokens: {' '.join(tokens)}")
                logger.info(f"input_ids: {' '.join(map(str, input_ids))}")
                logger.info(f"input_mask: {' '.join(map(str, input_mask))}")
                logger.info(f"segment_ids: {' '.join(map(str, segment_ids))}")
            # if is_training:
                logger.info(f"label: {label}")

        features.append(
            InputFeatures(
                choices_features = choices_features,
                label = label
            )
        )

    # plt.style.use('ggplot')
    # plt.xlabel('Number of words in Article')
    # plt.ylabel('Frequency')
    # plt.title('Task 2 Train Set Graph')
    # plt.hist(num_tokens_article , bins = 100);
    # plt.show();
    # print(len(examples))
    # print(count)

    return features

"""Some Custom functions : For optimisation !"""

def copy_optimizer_params_to_model(named_params_model, named_params_optimizer):
    """ Utility function for optimize_on_cpu and 16-bits training.
        Copy the parameters optimized on CPU/RAM back to the model on GPU
    """
    for (name_opti, param_opti), (name_model, param_model) in zip(named_params_optimizer, named_params_model):
        if name_opti != name_model:
            logger.error("name_opti != name_model: {} {}".format(name_opti, name_model))
            raise ValueError
        param_model.data.copy_(param_opti.data)

def set_optimizer_params_grad(named_params_optimizer, named_params_model, test_nan=False):
    """ Utility function for optimize_on_cpu and 16-bits training.
        Copy the gradient of the GPU parameters to the CPU/RAMM copy of the model
    """
    is_nan = False
    for (name_opti, param_opti), (name_model, param_model) in zip(named_params_optimizer, named_params_model):
        if name_opti != name_model:
            logger.error("name_opti != name_model: {} {}".format(name_opti, name_model))
            raise ValueError
        if param_model.grad is not None:
            if test_nan and torch.isnan(param_model.grad).sum() > 0:
                is_nan = True
            if param_opti.grad is None:
                param_opti.grad = torch.nn.Parameter(param_opti.data.new().resize_(*param_opti.data.size()))
            param_opti.grad.data.copy_(param_model.grad.data)
        else:
            param_opti.grad = None
    return is_nan

"""Set device first and tokenizer.

Now Prepare The MODEL :) :)
"""

#Set device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
n_gpu = torch.cuda.device_count()
# print(device)
# print(torch.cuda.get_device_name())

train_batch_size = int(train_batch_size / gradient_accumulation_steps)
#Initialise seeds
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed_all(seed)

if n_gpu > 0:
    torch.cuda.manual_seed_all(seed)


#Get Tokenizer
tokenizer = BertTokenizer.from_pretrained('bert-base-uncased', do_lower_case=True)

# Prepare model
model = BertForMultipleChoice.from_pretrained('bert-base-uncased',
    num_choices = 5
)

"""Move the model to GPU and also prints the model : 

12 Encoder Layers

1 Pooler Layer

1 Dropout layer

1 Final Classifier layer
"""

if fp16:
    model.half()

if n_gpu > 1:
    model = torch.nn.DataParallel(model)

model.to(device)

# Get the parameters of the model. 
# All the hidden weights of the model

if fp16:
    param_optimizer = [(n, param.clone().detach().to('cpu').float().requires_grad_()) \
                        for n, param in model.named_parameters()]
elif optimize_on_cpu:
    param_optimizer = [(n, param.clone().detach().to('cpu').requires_grad_()) \
                        for n, param in model.named_parameters()]
else:
    param_optimizer = list(model.named_parameters())
# print(param_optimizer)

no_decay = ['bias', 'gamma', 'beta']
optimizer_grouped_parameters = [
    {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay_rate': 0.01},
    {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay_rate': 0.0}
    ]

# Get the train examples from the csv file
train_examples = read_examples(os.path.join(data_dir_1 + train_file_1), True )
num_train_steps = int(len(train_examples) / train_batch_size / gradient_accumulation_steps * num_train_epochs)

t_total = num_train_steps

optimizer = BertAdam(optimizer_grouped_parameters,
                         lr = learning_rate,
                         warmup = warmup_proportion,
                         t_total = t_total)

"""**Let the Training Begin! **

To toggle the mode of model to train, do model.train() and for eval, do model.eval()
"""

# Define Accuracy check metrics and training utils

def epoch_time(start_time, end_time):
    elapsed_time = end_time - start_time
    elapsed_mins = int(elapsed_time / 60)
    elapsed_secs = int(elapsed_time - (elapsed_mins * 60))
    return elapsed_mins, elapsed_secs

def select_field(features, field):
    return [
        [
            choice[field]
            for choice in feature.choices_features
        ]
        for feature in features
    ]

def classifiction_metric(preds, labels, label_list):
    """ The Metric of classification, input should be numpy format """

    acc = metrics.accuracy_score(labels, preds)

    labels_list = [i for i in range(len(label_list))]

    report = metrics.classification_report(
        labels, preds, labels=labels_list, target_names=label_list, digits=5, output_dict=True)

    return acc, report

# Training Step : 

global_step = 0
if do_train:
    train_features = convert_examples_to_features(
        train_examples, tokenizer, max_seq_length
        )
    
    logger.info("***** Running training *****")
    logger.info("  Num examples = %d", len(train_examples))
    logger.info("  Batch size = %d", train_batch_size)
    logger.info("  Num steps = %d", num_train_steps)

    # Convert lists into tensors 
    all_input_ids = torch.tensor(select_field(train_features, 'input_ids'), dtype=torch.long)
    all_input_mask = torch.tensor(select_field(train_features, 'input_mask'), dtype=torch.long)
    all_segment_ids = torch.tensor(select_field(train_features, 'segment_ids'), dtype=torch.long)
    all_label = torch.tensor([f.label for f in train_features], dtype=torch.long)

    # Prepare TensorDataset, read here : https://pytorch.org/cppdocs/api/structtorch_1_1data_1_1datasets_1_1_tensor_dataset.html
    train_data = TensorDataset(all_input_ids, all_input_mask, all_segment_ids, all_label)

    train_sampler = RandomSampler(train_data)

    train_dataloader = DataLoader(train_data, sampler=train_sampler, batch_size=train_batch_size)

    model.train()
    for _ in trange(int(num_train_epochs), desc="Epoch"):
        tr_loss = 0
        nb_tr_examples, nb_tr_steps = 0, 0
        # all_preds = np.array([], dtype=int)
        # all_labels = np.array([], dtype=int)

        for step, batch in enumerate(tqdm(train_dataloader, desc="Iteration")):
            batch = tuple(t.to(device) for t in batch)
            input_ids, input_mask, segment_ids, label_ids = batch
            loss = model(input_ids, segment_ids, input_mask, label_ids)
            if n_gpu > 1:
                loss = loss.mean() # mean() to average on multi-gpu.
            if fp16 and loss_scale != 1.0:
                # rescale loss for fp16 training
                # see https://docs.nvidia.com/deeplearning/sdk/mixed-precision-training/index.html
                loss = loss * loss_scale
            if gradient_accumulation_steps > 1:
                loss = loss / gradient_accumulation_steps
            loss.backward()
            tr_loss += loss.item()
            nb_tr_examples += input_ids.size(0)
            nb_tr_steps += 1
            if (step + 1) % gradient_accumulation_steps == 0:
                if fp16 or optimize_on_cpu:
                    if fp16 and loss_scale != 1.0:
                        # scale down gradients for fp16 training
                        for param in model.parameters():
                            if param.grad is not None:
                                param.grad.data = param.grad.data / loss_scale
                    is_nan = set_optimizer_params_grad(param_optimizer, model.named_parameters(), test_nan=True)
                    if is_nan:
                        logger.info("FP16 TRAINING: Nan in gradients, reducing loss scaling")
                        loss_scale = loss_scale / 2
                        model.zero_grad()
                        continue
                    optimizer.step()
                    copy_optimizer_params_to_model(model.named_parameters(), param_optimizer)
                else:
                    optimizer.step()

                train_loss = tr_loss / nb_tr_steps
                print("Training loss : ", train_loss)

                model.zero_grad()
                global_step += 1

def accuracy(out, labels):
    outputs = np.argmax(out, axis=1)
    return np.sum(outputs == labels)

eval_examples = read_examples(os.path.join(data_dir_1 + dev_file_1), False)
eval_features = convert_examples_to_features(
    eval_examples, tokenizer, max_seq_length)

logger.info("***** Running evaluation *****")
logger.info("  Num examples = %d", len(eval_examples))
logger.info("  Batch size = %d", eval_batch_size)

all_input_ids = torch.tensor(select_field(eval_features, 'input_ids'), dtype=torch.long)
all_input_mask = torch.tensor(select_field(eval_features, 'input_mask'), dtype=torch.long)
all_segment_ids = torch.tensor(select_field(eval_features, 'segment_ids'), dtype=torch.long)
all_label = torch.tensor([f.label for f in eval_features], dtype=torch.long)
eval_data = TensorDataset(all_input_ids, all_input_mask, all_segment_ids, all_label)
# Run prediction for full data
eval_sampler = SequentialSampler(eval_data)
eval_dataloader = DataLoader(eval_data, sampler=eval_sampler, batch_size=eval_batch_size)

model.eval()
eval_loss, eval_accuracy = 0, 0
nb_eval_steps, nb_eval_examples = 0, 0
for input_ids, input_mask, segment_ids, label_ids in eval_dataloader:
    input_ids = input_ids.to(device)
    input_mask = input_mask.to(device)
    segment_ids = segment_ids.to(device)
    label_ids = label_ids.to(device)

    with torch.no_grad():
        tmp_eval_loss = model(input_ids, segment_ids, input_mask, label_ids)
        logits = model(input_ids, segment_ids, input_mask)

    logits = logits.detach().cpu().numpy()
    label_ids = label_ids.to('cpu').numpy()
    tmp_eval_accuracy = accuracy(logits, label_ids)

    eval_loss += tmp_eval_loss.mean().item()
    eval_accuracy += tmp_eval_accuracy

    nb_eval_examples += input_ids.size(0)
    nb_eval_steps += 1

eval_loss = eval_loss / nb_eval_steps
eval_accuracy = eval_accuracy / nb_eval_examples

result = {'eval_loss': eval_loss,
          'eval_accuracy': eval_accuracy,
          'global_step': global_step,
          'loss': tr_loss/nb_tr_steps}

print(result)
