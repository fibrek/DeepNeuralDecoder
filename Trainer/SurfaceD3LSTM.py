# ------------------------------------------------------------------------------
# 
#    SurfaceD3 trainer. Use 2 RNNs each with 1 LSTM cell of replication 3.
#
#    Copyright (C) 2017 Pooya Ronagh
# 
# ------------------------------------------------------------------------------

from builtins import range
import numpy as np
import tensorflow as tf
import sys
from util import y2indicator
import threading
import sys
import os
import json
from time import localtime, strftime, clock

%matplotlib inline
import matplotlib
import matplotlib.pyplot as plt

import bayesopt
from bayesoptmodule import BayesOptContinuous, BayesOptDiscrete

# The Surface code generator matrices and look up table
gZ = np.matrix([[1, 0, 0, 1, 0, 0, 0, 0, 0], \
                [0, 1, 1, 0, 1, 1, 0, 0, 0], \
                [0, 0, 0, 1, 1, 0, 1, 1, 0], \
                [0, 0, 0, 0, 0, 1, 0, 0, 1]]).astype(np.int32);
gX = np.matrix([[1, 1, 0, 1, 1, 0, 0, 0, 0], \
                [0, 0, 0, 0, 0, 0, 1, 1, 0], \
                [0, 1, 1, 0, 0, 0, 0, 0, 0], \
                [0, 0, 0, 0, 1, 1, 0, 1, 1]]).astype(np.int32);
XcorrectionMat = np.matrix([[0, 0, 0, 0, 0, 0, 0, 0, 0], \
                            [0, 0, 0, 0, 0, 0, 0, 0, 1], \
                            [0, 0, 0, 0, 0, 0, 1, 0, 0], \
                            [0, 0, 0, 0, 1, 1, 0, 0, 0], \
                            [0, 1, 0, 0, 0, 0, 0, 0, 0], \
                            [0, 0, 0, 0, 0, 1, 0, 0, 0], \
                            [0, 0, 0, 0, 1, 0, 0, 0, 0], \
                            [0, 0, 0, 0, 1, 0, 0, 0, 1], \
                            [1, 0, 0, 0, 0, 0, 0, 0, 0], \
                            [1, 0, 0, 0, 0, 0, 0, 0, 1], \
                            [0, 0, 0, 1, 0, 0, 0, 0, 0], \
                            [0, 0, 0, 1, 0, 0, 0, 0, 1], \
                            [1, 1, 0, 0, 0, 0, 0, 0, 0], \
                            [1, 0, 0, 0, 0, 1, 0, 0, 0], \
                            [1, 0, 0, 0, 1, 0, 0, 0, 0], \
                            [0, 0, 0, 1, 0, 1, 0, 0, 0]]).astype(np.int32);
ZcorrectionMat = np.matrix([[0, 0, 0, 0, 0, 0, 0, 0, 0], \
                            [0, 0, 0, 0, 0, 1, 0, 0, 0], \
                            [0, 0, 1, 0, 0, 0, 0, 0, 0], \
                            [0, 1, 0, 0, 1, 0, 0, 0, 0], \
                            [0, 0, 0, 0, 0, 0, 1, 0, 0], \
                            [0, 0, 0, 0, 0, 0, 0, 1, 0], \
                            [0, 0, 1, 0, 0, 0, 1, 0, 0], \
                            [0, 0, 1, 0, 0, 0, 0, 1, 0], \
                            [1, 0, 0, 0, 0, 0, 0, 0, 0], \
                            [0, 0, 0, 0, 1, 0, 0, 0, 0], \
                            [0, 1, 0, 0, 0, 0, 0, 0, 0], \
                            [0, 1, 0, 0, 0, 1, 0, 0, 0], \
                            [1, 0, 0, 0, 0, 0, 1, 0, 0], \
                            [1, 0, 0, 0, 0, 0, 0, 1, 0], \
                            [0, 1, 0, 0, 0, 0, 1, 0, 0], \
                            [0, 1, 0, 0, 0, 0, 0, 1, 0]]).astype(np.int32);
ZL = np.matrix([[1,0,0,0,1,0,0,0,1]]).astype(np.int32);
XL = np.matrix([[0,0,1,0,1,0,1,0,0]]).astype(np.int32);

err_keys= ['errX3', 'errZ3']
syn_keys= ['synX', 'synZ']

class Data:

    def __init__(self, data):
        self.input= {}
        self.output= {}
        self.output_ind= {}
        self.input['errX3']= data['synX'].reshape(-1, 3, 4)
        self.input['errZ3']= data['synZ'].reshape(-1, 3, 4)
        for key in err_keys:
            self.output[key]= data[key]
        for key in err_keys:
            self.output_ind[key]=y2indicator(data[key],2**9).astype(np.float32)

def io_data_factory(data, test_size):

    train_data_arg = {key:data[key][:-test_size,] for key in data.keys()}
    test_data_arg  = {key:data[key][-test_size:,] for key in data.keys()}
    train_data = Data(train_data_arg)
    test_data = Data(test_data_arg)
    return train_data, test_data

def find_logical_fault(recovery, err, key):

    p_binary= '{0:09b}'.format(recovery)
    t_binary= '{0:09b}'.format(int(err))
    err_list= [int(a!=b) for a, b in zip(p_binary, t_binary)]
    err= np.matrix(err_list).astype(np.int32)
    if (key=='errX3'):
        syndrome= np.dot(gZ, err.transpose()) % 2
        correction_index= np.asscalar(np.dot([[8, 4, 2, 1]], syndrome))
        correction = XcorrectionMat[correction_index,:]
        errFinal = (correction + err) % 2
        logical_err = np.dot(ZL, errFinal.transpose()) % 2
        return logical_err

    elif (key=='errZ3'):
        syndrome= np.dot(gX, err.transpose()) % 2
        correction_index= np.asscalar(np.dot([[8, 4, 2, 1]], syndrome))
        correction = ZcorrectionMat[correction_index,:]
        errFinal = (correction + err) % 2
        logical_err = np.dot(XL, errFinal.transpose()) % 2
        return logical_err

    else: print('Key not recognized.')

def num_logical_fault(prediction, test):

    error_counter= 0.0
    for i in range(len(prediction[err_keys[0]])):
        for key in err_keys:
            if (find_logical_fault(prediction[key][i],test.output[key][i],key)):
                error_counter+=1
                break
    return error_counter/len(prediction[err_keys[0]])

def get_data(filename):

    data= {}
    for key in syn_keys:
        data[key]= []
    for key in err_keys:
        data[key]= []
    with open(filename) as file:
        first_line = file.readline();
        p, lu_avg, lu_std, data_size = first_line.split(' ')
        p= float(p)
        lu_avg= float(lu_avg)
        lu_std= float(lu_std)
        data_size= int(data_size)
        for line in file.readlines():
            line_list= line.split(' ')
            data['synX'].append([bit for bit in ''.join(line_list[0:3])])
            data['synZ'].append([bit for bit in ''.join(line_list[6:9])])
            data['errX3'].append([int(line_list[5],2)])
            data['errZ3'].append([int(line_list[8],2)])
    for key in data.keys():
        data[key]= np.array(data[key]).astype(np.float32)
    return data, p, lu_avg, lu_std, data_size

def train(param, train_data, test_data, \
          num_classes, num_inputs, input_size, n_batches):

    prediction= {}
    verbose= param['usr']['verbose']
    batch_size= param['opt']['batch size']
    learning_rate= param['opt']['learning rate']
    num_iterations= param['opt']['iterations']
    momentum_val= param['opt']['momentum']
    decay_rate= param['opt']['decay']
    num_hidden= param['nn']['num hidden'] 
    W_std= param['nn']['W std'] 
    b_std= param['nn']['b std'] 

    # define all parts of the tf graph
    tf.reset_default_graph()
    x = {}
    y = {}
    lstm = {}
    lstmOut = {}
    W= {}
    b= {}
    logits= {}
    loss= {}
    predict= {}
    
    for key in err_keys:
        with tf.variable_scope(key):

            x[key] = tf.placeholder(tf.float32, [None, num_inputs, input_size])
            y[key] = tf.placeholder(tf.float32, [None, num_classes])
            lstm[key] = tf.contrib.rnn.LSTMCell(num_hidden)
            lstmOut[key], _ = tf.nn.dynamic_rnn(\
                lstm[key], x[key], dtype=tf.float32)
            W[key]= tf.Variable(\
                tf.random_normal([num_hidden,num_classes], stddev=W_std))
            b[key]= tf.Variable(tf.random_normal([num_classes], stddev=b_std))
            logits[key]= tf.matmul(lstmOut[key][:,-1,:], W[key]) + b[key]
            loss[key]= tf.nn.softmax_cross_entropy_with_logits(\
                logits=logits[key], labels=y[key])
            predict[key]= tf.argmax(logits[key], 1)
    
    cost= tf.reduce_sum(sum(loss[key] for key in err_keys))
    train = tf.train.RMSPropOptimizer(\
        learning_rate, decay=decay_rate, momentum=momentum_val).minimize(cost)
    init = tf.global_variables_initializer()
    costs= []

    with tf.Session() as session:
        if (verbose): print('session begins '),
        session.run(init)

        for i in range(num_iterations):
            if (verbose): print('.'),

            for j in range(n_batches):
                beg= j * batch_size
                end= j * batch_size + batch_size
                feed_dict={}
                for key in err_keys:
                    feed_dict[x[key]]= train_data.input[key][beg:end,]
                    feed_dict[y[key]]= train_data.output_ind[key][beg:end,]
                session.run(train, feed_dict)

            feed_dict={}
            for key in err_keys:
                feed_dict[x[key]]= test_data.input[key]
                feed_dict[y[key]]= test_data.output_ind[key]
            test_cost = session.run(cost, feed_dict)
            costs.append(test_cost)

        for key in err_keys:
            prediction[key] = session.run(predict[key], \
                feed_dict= {x[key]: test_data.input[key]})
        if (verbose): print(' session ends.')

    plt.plot(costs)
    plt.show()
    return num_logical_fault(prediction, test_data)

### Run an entire benchmark
# [-4.19456682,  0.85001536,  0.91390672,  5.00913479, -1.81279482]
# 1. # 2. learning rate= 10**x[1] 
# 2. # 4. momentum= x[3] 
# 3. # 5. decay= x[4]
# 4.  # 6. num hidden= int(x[5] * 10)
# 5. # 7. W std= 10**x[6]

param= {}
param['nn']= {}
param['opt']= {}
param['data']= {}
param['usr']= {}
param['nn']['num hidden']= 50
param['nn']['W std']= 10.0**(-1.81279482)
param['nn']['b std']= 0.0
param['opt']['batch size']= 1000
param['opt']['learning rate']= 10.0**(-4.19456682)
param['opt']['iterations']= 20
param['opt']['momentum']= 0.85001536
param['opt']['decay']= 0.91390672
param['data']['test fraction']= 0.1
param['usr']['verbose']= True
 
verbose= param['usr']['verbose']
output= []
num_classes= 2**9
num_inputs= 3
input_size= 4

datafolder= '../../Data/SurfaceD3/e-05/'
file_list= os.listdir(datafolder)

for filename in file_list:
    # Read data and find how much null syndromes to assume for error_scale
    print("Reading data from " + filename)
    raw_data, p, lu_avg, lu_std, data_size = get_data(datafolder + filename)

    test_fraction= param['data']['test fraction']
    total_size= np.shape(raw_data['synX'])[0]
    test_size= int(test_fraction * total_size)
    train_data, test_data = io_data_factory(raw_data, test_size)

    batch_size= param['opt']['batch size']
    train_size= total_size - test_size
    n_batches = train_size // batch_size
    error_scale= 1.0*total_size/data_size

    avg= train(param, train_data, test_data, \
        num_classes, num_inputs, input_size, n_batches)

    run_log= {}
    run_log['data']= {}
    run_log['opt']= {}
    run_log['res']= {}
    run_log['data']['path']= filename
    run_log['data']['fault scale']= error_scale
    run_log['data']['total data size']= total_size
    run_log['data']['test set size']= test_size
    run_log['opt']['batch size']= batch_size
    run_log['opt']['number of batches']= n_batches
    run_log['res']['p']= p
    run_log['res']['lu avg']= lu_avg
    run_log['res']['lu std']= lu_std
    run_log['res']['nn avg'] = error_scale * avg
    run_log['res']['nn std'] = 0
    output.append(run_log)

outfilename = strftime("%Y-%m-%d-%H-%M-%S", localtime())
f = open('../Reports/SurfaceD3/' + outfilename + '.json', 'w')
f.write(json.dumps(output, indent=2))
f.close()