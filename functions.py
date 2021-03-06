from __future__ import division
import mxnet as mx
import numpy as np
import logging,os
import copy
import urllib
import scipy

from scipy import special
import logging,os,sys
from scipy import stats
from random import shuffle
from sklearn.metrics import accuracy_score

import random

class eps_greedy():
  def __init__(self, epsilon):
    self.epsilon = epsilon
    self.t = 0
    #self.counts = counts
    #self.values = values
    return

  def initialize(self, n_arms):
    self.counts = [0 for col in range(n_arms)]
    self.values = [0.0 for col in range(n_arms)]
    return

  def select_arm(self):
    if np.random.uniform(0,1) > self.epsilon and max(self.values) > 0:
      return np.argmax(self.values)
    else:
      return random.randrange(len(self.values))

  def update(self, chosen_arm, reward):
    self.counts[chosen_arm] = self.counts[chosen_arm] + 1
    n = self.counts[chosen_arm]

    value = self.values[chosen_arm]
    new_value = ((n - 1) / float(n)) * value + (1 / float(n)) * reward
    self.values[chosen_arm] = new_value
    return

class eps_decay_greedy():
  def __init__(self, epsilon):
    self.epsilon = epsilon
    self.t = 0
    #self.counts = counts
    #self.values = values
    return

  def initialize(self, n_arms):
    self.n_arms = n_arms
    self.counts = [0 for col in range(n_arms)]
    self.values = [0.0 for col in range(n_arms)]
    return

  def select_arm(self):
    if np.random.uniform(0,1) > 1./(1 + self.t/self.n_arms) and max(self.values) > 0:
      return np.argmax(self.values)
    else:
      return random.randrange(len(self.values))

  def update(self, chosen_arm, reward):
    self.t = self.t + 1
    self.counts[chosen_arm] = self.counts[chosen_arm] + 1
    n = self.counts[chosen_arm]

    value = self.values[chosen_arm]
    new_value = ((n - 1) / float(n)) * value + (1 / float(n)) * reward
    self.values[chosen_arm] = new_value
    return

def price_accuracy(price, setting, fixp = 0.85, linear_min = 0.6, linear_max = 0.8):
    # generate underlying probability under various price setting
    # Fix, Concave, Aysmptotic, Linear, Ceiling
    setting = setting.lower()
    assert setting in ['fix', 'concave', 'asymptotic', 'linear', 'ceiling'], "unknown setting"
    if setting == 'fix':
        return fixp
    if setting == 'concave':
        return 0.48 + 0.066 * (100 * price) - 0.0022 * (100 * price) ** 2
    if setting == 'asymptotic':
        return 1 - 1./(100 * price)
    if setting == 'linear':
        return (linear_max - linear_min)/(0.25 - 0.02) * price  + (linear_min - 0.02 * (linear_max - linear_min)/(0.25 - 0.02))


def generate_workers(m,k,gamma,class_wise, price_setting = False, p_setting = 'fix', price = 0.02, fixp = 0.85, linear_min = 0.6, linear_max = 0.8):
    # Generating worker confusion matrices according to class-wise hammer-spammer distribution if class_wise ==1
    # Generating worker confusion matrices according to hammer-spammer distribution if class_wise ==0    
    # One row for each true class and columns for given answers
    
    #initializing confusion matrices with all entries being equal to 1/k that is corresponding to a spammer worker.
    conf = (1/float(k))*np.ones((m,k,k))

    if price_setting:
        accuracy = price_accuracy(price, p_setting, fixp, linear_min, linear_max)
    # a loop to generate confusion matrix for each worker 
    for i in range(m): 
        # if class_wise ==0 then generating worker confusion matrix according to hammer-spammer distribution
        if(class_wise==0):
            #letting the confusion matrix to be identity with probability gamma 

            if(np.random.uniform(0,1) < gamma):
                #original 
                #conf[i] = np.identity(k)
                #drop prob of perfect worker a little  
                if price_setting:
                    conf[i] = conf[i]+np.identity(k) * (1/float(k) - accuracy)/(accuracy - 1) 
                    conf[i] = np.divide(conf[i],np.outer(np.sum(conf[i],axis =1),np.ones(k)))
                else:    
                    conf[i] = conf[i]+np.identity(k) 
                    conf[i] = np.divide(conf[i],np.outer(np.sum(conf[i],axis =1),np.ones(k)))
                #beta distribution 
                #conf[i] = conf[i]+np.identity(k)*np.random.beta(2,0.5)
                #conf[i] = np.divide(conf[i],np.outer(np.sum(conf[i],axis =1),np.ones(k)))
            # To avoid numerical issues changing the spammer matrix each element slightly    
            else:
                conf[i] = conf[i] + 0.01*np.identity(k)
                conf[i] = np.divide(conf[i],np.outer(np.sum(conf[i],axis =1),np.ones(k)))        
        else:
            # if class_wise ==1 then generating each class separately according to hammer-spammer distribution    
            for j in range(k):
                # with probability gamma letting the worker to be hammer for the j-th class
                if(np.random.uniform(0,1) < gamma):
                    conf[i,j,:] = 0
                    conf[i,j,j] = 1 
                # otherwise letting the worker to be spammer for the j-th class. 
                # again to avoid numerical issues changing the spammer distribution slighltly 
                # by generating uniform random variable between 0.1 and 0.11
                else:
                    conf[i,j,:] = 1
                    conf[i,j,j] = 1 + np.random.uniform(0.1,0.11)
                    conf[i,j,:] = conf[i,j,:]/np.sum(conf[i,j,:])
    # returining the confusion matrices 
    return conf

def generate_labels_weight(fname,n,n1,repeat,conf):
    # extracting the number of workers and the number of classes from the confusion matrices
    m, k  = conf.shape[0], conf.shape[1]    
    # a numpy array to store true class of the training examples
    class_train = np.zeros((n), dtype = np.int)
    # reading the train.lst file and storing true class of each training example
    with open(fname[1],"r") as f1:
        content = f1.readlines()
    for i in range(n):
        content_lst = content[i].split("\t")
        class_train[i] = int(float(content_lst[1]))
    
    # a dictionary to store noisy labels generated using the worker confusion matrices for each training example  
    workers_train_label = {}
    # the dictionary contains "repeat" number of numpy arrays with keys named "softmax_0_label", where 0 varies
    # each array has the noisy labels for the training examples given by the workers
    for i in range(repeat):
        workers_train_label['softmax' + str(i) + '_label'] = np.zeros((n,k))   
    
    # Generating noisy labels according the worker confusion matrices and the true labels of the examples
    # a variable to store one-hot noisy label, note that each label belongs to one of the k classes
    resp = np.zeros((n,m,k))
    # a variable to store identity of the workers that are assigned to the i-th example
    # note that "repeat" number of workers are randomly chosen from the set of [m] workers and assigned to each example
    workers_this_example = np.zeros((n,repeat),dtype=np.int)
    
    # iterating over each training example
    for i in range(n):
        # randomly selecting "repeat" number of workers for the i-th example
        workers_this_example[i] = np.sort(np.random.choice(m,repeat,replace=False))
        count = 0
        # for each randomly chosen worker generating noisy label according to her confusion matrix and the true label
        for j in workers_this_example[i]:
            # using the row of the confusion matrix corresponding to the true label generating the noisy label
            temp_rand = np.random.multinomial(1,conf[j,class_train[i],:])
            # storing the noisy label in the resp variable 
            resp[i,j,:] = temp_rand
            # storing the noisy label in the dictionary
            workers_train_label['softmax' + str(count) + '_label'][i] = temp_rand
            count = count +1 
            
    # note that in the dictionary each numpy array is of size only (n,k). 
    # The dictionary is passed to the deep learning module
    # however, the resp variable is a numpy array of size (n,m,k).
    # it is used for performing expectation maximization on the noisy labels

    # initializing a dictionary to store one-hot representation of the true labels for the validation set
    workers_val_label = {}
    # the dictionary contains "repeat" number of numpy arrays with keys named "softmax_0_label", where 0 varies
    # each array has the true labels of the examples in the validation set
    workers_val_label['softmax' + str(0) + '_label'] = np.zeros((n1,k))  
    
    # reading the .lst file for the validation set
    content_val_lst = np.genfromtxt(fname[3], delimiter='\t')
    # storing the true labels of the examples in the validation set in the dictionary
    for i in range(n1):
        workers_val_label['softmax' + str(0) + '_label'][i][int(content_val_lst[i,1])] = 1
    
    # returning the noisy responses of the workers stored in the resp numpy array, 
    # the noisy labels stored in the dictionary that is used by the deep learning module
    # the true lables of the examples in the validation set stored in the dictionary
    # identity of the workers that are assigned to th each example in the training set
    return resp, workers_train_label, workers_val_label, workers_this_example

def majority_voting(resp):
    # computes majority voting label
    # ties are broken uniformly at random
    n = resp.shape[0]
    k = resp.shape[2]
    pred_mv = np.zeros((n), dtype = np.int)
    for i in range(n):
        # finding all labels that have got maximum number of votes
        poss_pred = np.where(np.sum(resp[i],0) == np.max(np.sum(resp[i],0)))[0]
        shuffle(poss_pred)
        # choosing a label randomly among all the labels that have got the highest number of votes
        pred_mv[i] = poss_pred[0]   
    pred_mv_vec = np.zeros((n,k))
    # returning one-hot representation of the majority vote label
    pred_mv_vec[np.arange(n), pred_mv] = 1
    return pred_mv_vec

def post_prob_DS(resp_org,e_class,workers_this_example):
    # computes posterior probability distribution of the true label given the noisy labels annotated by the workers
    # and model prediction
    n = resp_org.shape[0]
    m = resp_org.shape[1]
    k = resp_org.shape[2]
    repeat = workers_this_example.shape[1]
    
    temp_class = np.zeros((n,k))
    e_conf = np.zeros((m,k,k))
    temp_conf = np.zeros((m,k,k))
    
    #Estimating confusion matrices of each worker by assuming model prediction "e_class" is the ground truth label
    for i in range(n):
        for j in workers_this_example[i]: #range(m)
            temp_conf[j,:,:] = temp_conf[j,:,:] + np.outer(e_class[i],resp_org[i,j])
    #regularizing confusion matrices to avoid numerical issues
    for j in range(m):  
        for r in range(k):
            if (np.sum(temp_conf[j,r,:]) ==0):
                # assuming worker is spammer for the particular class if there is no estimation for that class for that worker
                temp_conf[j,r,:] = 1/k
            else:
                # assuming there is a non-zero probability of each worker assigning labels for all the classes
                temp_conf[j,r,:][temp_conf[j,r,:]==0] = 1e-10
        e_conf[j,:,:] = np.divide(temp_conf[j,:,:],np.outer(np.sum(temp_conf[j,:,:],axis =1),np.ones(k)))
    # Estimating posterior distribution of the true labels using confusion matrices of the workers and the original
    # noisy labels annotated by the workers
    for i in range(n):
        for j in workers_this_example[i]: 
            if (np.sum(resp_org[i,j]) ==1):
                temp_class[i] = temp_class[i] + np.log(np.dot(e_conf[j,:,:],np.transpose(resp_org[i,j])))
        temp_class[i] = np.exp(temp_class[i])
        temp_class[i] = np.divide(temp_class[i],np.outer(np.sum(temp_class[i]),np.ones(k)))
        e_class[i] = temp_class[i]           
    return e_class

def estimate(price_level, setting, fname, m = 10, k = 10, gamma = 1, class_wise = 0 ):
    resp_org = np.array([]).reshape(100,0,10)
    cost_so_far = 0.
    for p in price_level:
        conf = generate_workers(m,k,gamma,class_wise, price_setting = True, p_setting = 'fix', price = 0.02, fixp = 0.85, linear_min = 0.6, linear_max = 0.8)
        resp_org1, workers_train_label_org, workers_val_label, workers_this_example = generate_labels_weight(fname,100,0,1,conf)
        resp_org = np.concatenate((resp_org, resp_org1), axis = 1)
        cost_so_far = cost_so_far + np.sum(resp_org1) * p
    pred = majority_voting(resp_org)
    est = [accuracy_score(pred, np.sum(resp_org[:,resp_org1.shape[1]*(i):resp_org1.shape[1]*(i+1),:],axis=1)) for i in range(len(price_level))]
    return est, cost_so_far

def redundancy(est, price_level, m, B, redundancy_level = np.arange(1,10)):
    delta = 0.05
    rec = dict()
    for p, price in zip(est,price_level):
        alpha = p
        samples = B / price
        for r in redundancy_level:
            gamma = 1./((1 - 2 * alpha) * np.sqrt(samples/r))
            #e = 2 ** 4 * gamma +  2**8*np.sqrt(m*np.log(2**6*m*delta)/(samples * r))
            e = 0.00
            beta = (p + e) ** r * sum([scipy.special.comb(r,u)/((p/(1-p))**u + (p/(1-p)) ** (r-u))  for u in list(np.arange(r))+[r]])
            upp_bound = np.sqrt(r)/((1 - 2 * beta) * np.sqrt(samples))
            rec[(price,r)] = upp_bound
    (price,r) = min(rec, key = rec.get)
    return r, price
