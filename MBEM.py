from __future__ import division
import mxnet as mx
import numpy as np
import logging,os
import copy
import urllib
import logging,os,sys
import matplotlib
matplotlib.use('Agg')
import scipy

from math import floor
from scipy import stats
from random import shuffle
from sklearn.metrics import accuracy_score

from functions import generate_workers, generate_labels_weight, majority_voting, post_prob_DS, estimate, redundancy
from resnet import train, max_val_epoch
import matplotlib.pyplot as plt

# Downloading data for CIFAR10
# The following function downloads .rec iterator and .lst files (MXNET iterators) for CIFAR10 
# that are used for training the deep learning model with noisy annotations
def download_cifar10():
    fname = ['train.rec', 'train.lst', 'val.rec', 'val.lst']
    testfile = urllib.URLopener()
    testfile.retrieve('http://data.mxnet.io/data/cifar10/cifar10_train.rec', fname[0])
    testfile.retrieve('http://data.mxnet.io/data/cifar10/cifar10_train.lst', fname[1])
    testfile.retrieve('http://data.mxnet.io/data/cifar10/cifar10_val.rec',   fname[2])
    testfile.retrieve('http://data.mxnet.io/data/cifar10/cifar10_val.lst',   fname[3])
    return fname
# download data
fname = download_cifar10()
# setting up values according to CIFAR10 dataset
# n is total number of training samples for CIFAR10
# n1 is the total number of test samples for CIFAR10 
# k is the number of classes
n, n1, k = 50000, 10000, 10
    
#setting the number of gpus that are available
gpus = '0,1,2,3' #'0,1,2,3' # if there are no gpus available set it to None.

# m is the number of workers,  gamma is the worker quality, 
# class_wise is the binary variable: takes value 1 if workers are class_wise hammer spammer 
# and 0 if workers are hammer-spammer
# k is the number of classification classes, 
# epochs is the number of epochs for ResNet model
m, gamma, class_wise, epochs, depth  = 100, 1, 0, 60, 20

price_levels = np.arange(0.02, 0.25, 0.01)
r_levels = np.arange(1,6)

#### main function ####    
def main(fname,n,n1,k,conf,samples,repeat,epochs,depth,gpus):    
    # defining the range of samples that are to be used for training the model
    valid = np.arange(0,samples,dtype='int64')
    # declaring the other samples to be invalid 
    invalid = np.arange(samples,n,dtype='int64')
    # calling function generate_labels_weight which generates noisy labels given the true labels 
    # the true lables of the examples are ascertained from the .lst files 
    # it takes as input the following:
    # name of the .lst files for the training set and the validation set
    # conf: the confusion matrices of the workers
    # repeat: number of redundant labels that need to be generated for each sample
    # for each i-th sample repeat number of workers are chosen randomly that labels the given sample
    # it returns a multi dimensional array resp_org: 
    # such that resp_org[i,j,k] is 0 vector if the a-th worker was not chosen to label the i-th example
    # else it is one-hot representation of the noisy label given by the j-th worker on the i-th example
    # workers_train_label_org: it is a dictionary. it contains "repeat" number of numpy arrays, each of size (n,k)
    # the arrays have the noisy labels given by the workers
    # workers_val_label: it is a dictionary. it contains one numpy array of size (n,k) 
    # that has true label of the examples in the validation set
    # workers_this_example: it is a numpy array of size (n,repeat).
    # it conatins identity of the worker that are used to generate "repeat" number of noisy labels for example    
    resp_org, workers_train_label_org, workers_val_label, workers_this_example = generate_labels_weight(fname,n,n1,repeat,conf)    
    #setting invalid ones 0, so that they are not used by deep learning module
    for r in range(repeat):
        workers_train_label_org['softmax'+ str(r) +'_label'][invalid] = 0       
    
    print "Algorithm: majority vote:\t\t",
    # running the baseline algorithm where the noisy labels are aggregated using the majority voting
    # calling majority voting function to aggregate the noisy labels
    pred_mv = majority_voting(resp_org[valid])    
    # call_train function takes as input the noisy labels "pred_mv", trains ResNet model for the given "depth"
    # for "epochs" run using the available "gpus". 
    # it prints the generalization error of the trained model.
    _, val_acc = call_train(n,samples,k,pred_mv,workers_val_label,fname,epochs,depth,gpus)
    print "generalization_error:  " + str(val_acc)
    mv_acc = val_acc

    print "Algorithm: weighted majority vote:\t", 
    # running the another baseline algorithm where the aggregation is performed using the weighted majority vote
    # creating a numpy array to store weighted majority vote labels
    naive_agg = np.zeros((n,k))
    # generating the weighted majority vote label using the original noisy labels stored in the 
    # dictionary "workers_train_label_org"
    for r in range(repeat):
        naive_agg = naive_agg + (1/repeat)*copy.deepcopy(workers_train_label_org['softmax'+ str(r) +'_label']) 
    # calling the "call_train" function which besides printing the generalization error 
    # returns model prediction on the training examples, which is being stored in the variable "naive_pred".
    naive_pred, val_acc = call_train(n,samples,k,naive_agg[valid],workers_val_label,fname,epochs,depth,gpus)
    print "generalization_error:  " + str(val_acc)
    wmv_acc = val_acc

    print "Algorithm: MBEM:\t\t\t",    
    # running the proposed algorithm "MBEM: model bootstrapped expectation maximization" 
    # computing posterior probabilities of the true labels given the noisy labels and the worker identities.
    # post_prob_DS function takes the noisy labels given by the workers "resp_org", model prediction obtained 
    # by running "weighted majority vote" algorithm, and the worker identities.
    probs_est_labels = post_prob_DS(resp_org[valid],naive_pred[valid],workers_this_example[valid])      
    algo_agg = np.zeros((n,k))    
    algo_agg[valid] = probs_est_labels
    # calling the "call_train" function with aggregated labels being the posterior probability distribution of the 
    # examples given the model prediction obtained using the "weighted majority vote" algorithm.
    _, val_acc = call_train(n,samples,k,algo_agg[valid],workers_val_label,fname,epochs,depth,gpus)
    print "generalization_error:  " + str(val_acc)
    mbem_acc = val_acc
    return mv_acc, wmv_acc, mbem_acc
    
def main_mab(fname,n,n1,k,conf,samples_l,samples_h,repeat,epochs,depth,gpus):    
    # defining the range of samples that are to be used for training the model
    valid = np.arange(samples_l,samples_h,dtype='int64')
    # declaring the other samples to be invalid 
    invalid = np.arange(0,samples_l,dtype = 'int64') + np.arange(samples,n,dtype='int64')   
    # calling function generate_labels_weight which generates noisy labels given the true labels 
    # the true lables of the examples are ascertained from the .lst files 
    # it takes as input the following:
    # name of the .lst files for the training set and the validation set
    # conf: the confusion matrices of the workers
    # repeat: number of redundant labels that need to be generated for each sample
    # for each i-th sample repeat number of workers are chosen randomly that labels the given sample
    # it returns a multi dimensional array resp_org: 
    # such that resp_org[i,j,k] is 0 vector if the a-th worker was not chosen to label the i-th example
    # else it is one-hot representation of the noisy label given by the j-th worker on the i-th example
    # workers_train_label_org: it is a dictionary. it contains "repeat" number of numpy arrays, each of size (n,k)
    # the arrays have the noisy labels given by the workers
    # workers_val_label: it is a dictionary. it contains one numpy array of size (n,k) 
    # that has true label of the examples in the validation set
    # workers_this_example: it is a numpy array of size (n,repeat).
    # it conatins identity of the worker that are used to generate "repeat" number of noisy labels for example    
    resp_org, workers_train_label_org, workers_val_label, workers_this_example = generate_labels_weight(fname,n,n1,repeat,conf)    
    #setting invalid ones 0, so that they are not used by deep learning module
    for r in range(repeat):
        workers_train_label_org['softmax'+ str(r) +'_label'][invalid] = 0       
    
    print "Algorithm: majority vote:\t\t",
    # running the baseline algorithm where the noisy labels are aggregated using the majority voting
    # calling majority voting function to aggregate the noisy labels
    pred_mv = majority_voting(resp_org[valid])    
    # call_train function takes as input the noisy labels "pred_mv", trains ResNet model for the given "depth"
    # for "epochs" run using the available "gpus". 
    # it prints the generalization error of the trained model.
    pred_mv_res, val_acc = call_train(n,samples,k,pred_mv,workers_val_label,fname,epochs,depth,gpus)
    print "generalization_error:  " + str(val_acc)
    mv_acc = val_acc
    model_acc = accuracy_score(pred_mv, pred_mv_res)

    print "Algorithm: weighted majority vote:\t", 
    # running the another baseline algorithm where the aggregation is performed using the weighted majority vote
    # creating a numpy array to store weighted majority vote labels
    #naive_agg = np.zeros((n,k))
    # generating the weighted majority vote label using the original noisy labels stored in the 
    # dictionary "workers_train_label_org"
    #for r in range(repeat):
    #    naive_agg = naive_agg + (1/repeat)*copy.deepcopy(workers_train_label_org['softmax'+ str(r) +'_label']) 
    # calling the "call_train" function which besides printing the generalization error 
    # returns model prediction on the training examples, which is being stored in the variable "naive_pred".
    #naive_pred, val_acc = call_train(n,samples,k,naive_agg[valid],workers_val_label,fname,epochs,depth,gpus)
    print "generalization_error:  " + str(val_acc)
    #wmv_acc = val_acc

    #print "Algorithm: MBEM:\t\t\t",    
    # running the proposed algorithm "MBEM: model bootstrapped expectation maximization" 
    # computing posterior probabilities of the true labels given the noisy labels and the worker identities.
    # post_prob_DS function takes the noisy labels given by the workers "resp_org", model prediction obtained 
    # by running "weighted majority vote" algorithm, and the worker identities.
    
    #probs_est_labels = post_prob_DS(resp_org[valid],naive_pred[valid],workers_this_example[valid])      
    #algo_agg = np.zeros((n,k))    
    #algo_agg[valid] = probs_est_labels
    
    # calling the "call_train" function with aggregated labels being the posterior probability distribution of the 
    # examples given the model prediction obtained using the "weighted majority vote" algorithm.
    #_, val_acc = call_train(n,samples,k,algo_agg[valid],workers_val_label,fname,epochs,depth,gpus)
    #print "generalization_error:  " + str(val_acc)
    #mbem_acc = val_acc
    return model_acc, pred_mv

def call_train(n,samples,k,workers_train_label_use,workers_val_label,fname,epochs,depth,gpus):
    # this function takes as input aggregated labels of the training examples
    # along with name of the .rec files for training the ResNet model, depth of the model, number of epochs, and gpus information
    # it returns model prediction on the training examples.
    # we train the model twice first using the given aggregated labels and
    # second using the model prediction on the training examples on based on the first training
    # this aspect is not covered in the algorithm given in the paper. however, it works better in practice.
    # training the model twice in this fashion can be replaced by training once for sufficiently large number of epochs
    # first training of the model using the given aggregated labels 
    workers_train_label_use_core = np.zeros((n,k))
    workers_train_label_use_core[np.arange(samples,dtype=np.int)] = workers_train_label_use        
    pred_first_iter, val_acc = call_train_core(n,samples,k,workers_train_label_use_core,workers_val_label,fname,epochs,depth,gpus)
    # second training of the model using the model prediction on the training examples based on the first training.
    workers_train_label_use_core = np.zeros((n,k))
    workers_train_label_use_core[np.arange(samples,dtype=np.int)] = pred_first_iter[np.arange(samples)]
    pred_second_iter, val_acc = call_train_core(n,samples,k,workers_train_label_use_core,workers_val_label,fname,epochs,depth,gpus)
    return pred_second_iter, val_acc
    
def call_train_core(n,samples,k,workers_train_label_use_core,workers_val_label,fname,epochs,depth,gpus):
    # this function takes as input the same variables as the "call_train" function and it calls
    # the mxnet implementation of ResNet training module function "train"
    samples = int(samples) 
    workers_train_label = {} 
    workers_train_label['softmax0_label'] = workers_train_label_use_core  
    prediction, val_acc = train(gpus,fname,workers_train_label,workers_val_label,numepoch=epochs,batch_size=500,depth = depth,lr=0.5)
    model_pred = np.zeros((n,k))
    model_pred[np.arange(samples,dtype=np.int), np.argmax(prediction[0:samples],1)] = 1
    return model_pred, val_acc 


# calling  function to generate confusion matrices of workers
#conf = generate_workers(m,k,gamma,class_wise, price_setting = True, p_setting = 'fix', price = 0.02, fixp = 0.85, linear_min = 0.6, linear_max = 0.8)  

# calling the main function that takes as input the following:
# name of .rec iterators and .lst files that to operate on,
# worker confusion matrices, 
# number of epochs for running ResNet model, depth of the model,
# number of gpus available on the machine,
# samples: number of samples to be used for training the model,
# repeat: the number of redundant noisy labels to be used for each training example, 
# that are generated using the worker confusion mtrices
# it prints the generalization error of the model on set aside test data
# note that the samples*repeat is approximately same for each pair
# which implies that the total annotation budget is fixed.
#mv_his = []
#wmv_his = []
#mbem_his = []
#for repeat,samples in [[10,5000],[7,7000],[6,8000],[5,10000],[4,12500],[3,17000],[2,25000],[1,50000]]: 
#    print "\nnumber of training examples: " + str(samples) + "\t redundancy: " + str(repeat)
#    # calling the main function
#    mv_acc, wmv_acc, mbem_acc = main(fname,n,n1,k,conf,samples,repeat,epochs,depth,gpus)
#    mv_his.append(mv_acc)
#    wmv_his.append(wmv_acc)
#    mbem_acc.append(mbem_acc)

def main_price_setting(B = 1000, K = 10):
    for setting in ['fix', 'concave', 'asymptotic', 'linear']:
        print('Starting to price setting: ', setting)
        print('-----------------------------------------------------------')
        est, B_ini = estimate(price_levels, setting, fname)
        r,p = redundancy(est, price_levels, m, B, redundancy_level = np.arange(1,6))
        r = int(r)
        conf = generate_workers(m,k,gamma,class_wise, price_setting = True, p_setting = setting, price = p, fixp = 0.85, linear_min = 0.6, linear_max = 0.8)  
        print('Infered Strategy')
        print('r:',r,' p:',p)
        samples = int(floor(B*1. / p / r))
        mv_acc_i, wmv_acc_i, mbem_acc_i = main(fname,n,n1,k,conf,samples,r,epochs,depth,gpus)

        min_p = min(price_levels)
        conf = generate_workers(m,k,gamma,class_wise, price_setting = True, p_setting = setting, price = min_p, fixp = 0.85, linear_min = 0.6, linear_max = 0.8)  
        print "Min Strategy"
        mv_his = []
        wmv_his = []
        mbem_his = []
        for repeat in np.arange(1,6):
            samples = int(floor(B / min_p / repeat)) 
            print "\nnumber of training examples: " + str(samples) + "\t redundancy: " + str(repeat)
            # calling the main function
            mv_acc, wmv_acc, mbem_acc = main(fname,n,n1,k,conf,samples,repeat,epochs,depth,gpus)
            mv_his.append(mv_acc)
            wmv_his.append(wmv_acc)
            mbem_his.append(mbem_acc)
        plt.plot([1,2,3,4,5],mv_his, label = 'mv')
        plt.plot([1,2,3,4,5],wmv_his, label = 'wmv')
        plt.plot([1,2,3,4,5],mbem_his, label = 'mbem')
        plt.plot([1,2,3,4,5],[mbem_acc_i]*5, label = 'mbem_r')
        plt.legend()
        plt.savefig('Min_Strategy_'+setting + '.png')
        plt.close()
        max_p = max(price_levels)
        conf = generate_workers(m,k,gamma,class_wise, price_setting = True, p_setting = setting, price = max_p, fixp = 0.85, linear_min = 0.6, linear_max = 0.8)  
        print "Max Strategy"
        mv_his = []
        wmv_his = []
        mbem_his = []
        for repeat in np.arange(1,6):
            samples = int(floor(B / max_p / repeat))
            # calling the main function
            print "\nnumber of training examples: " + str(samples) + "\t redundancy: " + str(repeat)
            mv_acc, wmv_acc, mbem_acc = main(fname,n,n1,k,conf,samples,repeat,epochs,depth,gpus)
            mv_his.append(mv_acc)
            wmv_his.append(wmv_acc)
            mbem_his.append(mbem_acc)
        plt.plot([1,2,3,4,5],mv_his, label = 'mv')
        plt.plot([1,2,3,4,5],wmv_his, label = 'wmv')
        plt.plot([1,2,3,4,5],mbem_his, label = 'mbmv')
        plt.plot([1,2,3,4,5],[mbem_acc_i]*5, label = 'mbem_r')
        plt.legend()
        plt.savefig('Max_Strategy_' + setting + '.png')
        plt.close()

def multi_arm_main(B = 1000, K = 10, eps = 0.1, max_step = 250):
    for setting in ['fix','concave','asymptotic','linear']:
        cost_so_far = 0.
        n_total_arms = len(price_levels) * len(r_levels)
        p, r = np.meshgrid(price_levels, r_levels)
        p, r = p.reshape(-1), r.reshape(-1)
        arm_price_redundacy = list(zip(p,r))
        G_mv = eps_greedy(eps)
        G_decay_mv = eps_decay_greedy()
        G_mv.initialize(n_total_arms)
        G_decay_mv.initialize(n_total_arms)
        b = B / max_step
        conf = generate_workers(m,k,gamma,class_wise, price_setting = True, p_setting = setting, price = max_p, fixp = 0.85, linear_min = 0.6, linear_max = 0.8)  
        resp_org, workers_train_label_org, workers_val_label, workers_this_example = generate_labels_weight(fname,n,n1,r,conf) 
        samples_l = 0 
        pred_mv_res = np.empty(shape = (0,k))
        for step in range(max_step):
            cost_so_far += b
            print('Starting Majority Voting:')
            print('cost so far: ', cost_so_far)
            arm = G_mv.select_arm()
            p,r = arm_price_redundacy[arm]
            print('selecting p: ',p, ' | selecting r: 'r)
            samples = int(floor(b / p / r))
            samples_h = samples_l + samples
            mv_acc, pred_mv = main_mab(fname,n,n1,k,conf,samples_l, samples_h,r,epochs,depth,gpus)
            pred_mv_res = np.concatenate((pred_mv_res,pred_mv),axis=0)
            samples_l = samples_h
            reward = mv_acc
            G_mv.update(arm, reward)
        _, val_acc = call_train(n,samples_l,k,pred_mv_res,workers_val_label,fname,epochs,depth,gpus)
        print "final generalization_error:  " + str(val_acc)

multi_arm_main()