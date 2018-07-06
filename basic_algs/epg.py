import tensorflow as tf
import gym
import collections
import numpy as np
import os
#import multiprocessing
import threading
import random
#import operator
#from functools import reduce
import math
os.environ['TF_CPP_MIN_LOG_LEVEL'] = "3"

""" Evolved Policy Gradients for CartPole"""

BUFFER_SIZE = 512 # N
MEMORY_SIZE = 32
SAMPLE_SIZE = 64 # M
NUM_ACTIONS = 4
STATE_SPACE = 24
BATCH_SIZE = 32
tf.reset_default_graph()

def build_graph():
    epg_graph = tf.Graph()

    with epg_graph.as_default() as g:

        """ The ES memory takes as input a vector of ones.
        Acts as a vector of biases.
        """
        memory_scope = "memory"
        with tf.variable_scope(memory_scope):
            # memory units
            memory = tf.layers.dense(tf.ones([1, MEMORY_SIZE]), MEMORY_SIZE, activation=tf.nn.tanh, use_bias=False)

        # replicate memory to concate with M (BUFFER_SIZE) samples
        memory_tile = tf.tile(memory, [BUFFER_SIZE, 1])

        # replicate memory to concate with BATCH_SIZE samples
        memory_tile_batch = tf.tile(memory, [BATCH_SIZE, 1])

        memory_params = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=memory_scope)

        #memory_assign_plhs = {}
        #memory_assign_ops = []
        #for param in memory_params:
        #    param_value_plh = tf.placeholder(shape=param.get_shape(), dtype=tf.float32)
        #    assign_op = tf.assign(param, param_value_plh)
        #    memory_assign_plhs[param.name] = param_value_plh
        #    memory_assign_ops.append(assign_op)

        # require params be assigned before evaluating
        #with tf.control_dependencies(memory_assign_ops):
        #    memory_tile = tf.identity(memory_tile)

        # {state, termination_signal, reward}
        state_plh = tf.placeholder(shape=[BUFFER_SIZE, STATE_SPACE], dtype=tf.float32, name="state_plh")
        terminate_plh = tf.placeholder(shape=[BUFFER_SIZE, 1], dtype=tf.float32, name="terminate_plh")
        reward_plh = tf.placeholder(shape=[BUFFER_SIZE, 1], dtype=tf.float32, name="reward_plh")

        """ Policy Network operates on state
        operates on the state samples from the buffer N for context computation
        """
        initializer = tf.contrib.layers.variance_scaling_initializer()
        policy_scope = "policy"
        with tf.variable_scope(policy_scope) as scope:
            hidden = tf.layers.dense(state_plh, 64, activation=tf.nn.tanh, kernel_initializer=initializer)
            hidden = tf.layers.dense(hidden, 64, activation=tf.nn.tanh, kernel_initializer=initializer)
            policy = tf.layers.dense(hidden, NUM_ACTIONS, activation=None, kernel_initializer=initializer)
            #policy = tf.nn.softmax(policy, axis=1)
            policy = tf.nn.tanh(policy)

        """ Policy Network operates on state
        operates on a single state sample for computing action
        """
        state_sample_plh = tf.placeholder(shape=[1, STATE_SPACE], dtype=tf.float32, name="state_sample_plh")
        with tf.variable_scope(scope, reuse=True):
            hidden = tf.layers.dense(state_sample_plh, 64, activation=tf.nn.tanh, kernel_initializer=initializer)
            hidden = tf.layers.dense(hidden, 64, activation=tf.nn.tanh, kernel_initializer=initializer)
            policy_sample = tf.layers.dense(hidden, NUM_ACTIONS, activation=None, kernel_initializer=initializer)
            #policy_sample = tf.nn.softmax(policy_sample, axis=1)
            policy_sample = tf.nn.tanh(policy_sample)
            # sample action
        policy_sample = tf.identity(policy_sample, name="policy_sample")#tf.argmax(policy_sample, axis=1, name="policy_sample")

        """ Policy Network operates on state
        operates on a batch of samples for computing loss and gradints of policy and mem
        """
        state_batch_plh = tf.placeholder(shape=[BATCH_SIZE, STATE_SPACE], dtype=tf.float32, name="state_batch_plh")
        terminate_batch_plh = tf.placeholder(shape=[BATCH_SIZE, 1], dtype=tf.float32, name="terminate_batch_plh")
        reward_batch_plh = tf.placeholder(shape=[BATCH_SIZE, 1], dtype=tf.float32, name="reward_batch_plh")
        with tf.variable_scope(scope, reuse=True):
            hidden = tf.layers.dense(state_batch_plh, 64, activation=tf.nn.tanh, kernel_initializer=initializer)
            hidden = tf.layers.dense(hidden, 64, activation=tf.nn.tanh, kernel_initializer=initializer)
            policy_batch = tf.layers.dense(hidden, NUM_ACTIONS, activation=None, kernel_initializer=initializer)
            #policy_batch = tf.nn.softmax(policy_batch, axis=1)
            policy_batch = tf.nn.tanh(policy_batch)

        policy_params = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=policy_scope)


        # assign parameters to policy network, to allow for changing of params on each evaluations
        #policy_assign_plhs = {} # the placeholder for the params to assign
        #policy_assign_ops = [] # the actual assign ops
        #for param in policy_params:
        #    param_value_plh = tf.placeholder(shape=param.get_shape(), dtype=tf.float32)
        #    assign_op = tf.assign(param, param_value_plh)
        #    policy_assign_plhs[param.name] = param_value_plh
        #    policy_assign_ops.append(assign_op)

        # require parameters be assign before evaluating
        #with tf.control_dependencies(policy_assign_ops):
        #    policy = tf.identity(policy)


        """ context vector network, operates on N buffer samples
        these samples include N {state, termination_signal pairs}
        TF computes the rest of the required components: mem, action, policy distribution
        In this case we don't add the reward; the reward is optional since it can be inferred.
        """
        # ES update
        context_scope = "context"
        with tf.variable_scope(context_scope):
            # tf.cast(tf.expand_dims(tf.argmax(policy, axis=1), axis=1), tf.float32)
            context_input = tf.concat([state_plh, terminate_plh, reward_plh, policy, memory_tile, policy], axis=1)
            context_input = tf.expand_dims(context_input, axis=0)
            hidden = tf.layers.conv1d(context_input, 10, 8, strides=7, activation=tf.nn.elu, padding="same")
            hidden = tf.layers.conv1d(hidden, 10, 4, strides=2, activation=tf.nn.elu, padding="same")
            context = tf.layers.conv1d(hidden, 32, int(hidden.get_shape()[1]), strides=1, activation=tf.nn.elu, padding="valid")


        context = tf.squeeze(context, axis=0)

        #compute context batch
        context = tf.tile(context, [BATCH_SIZE, 1])

        #context_input = tf.squeeze(context_input, axis=0)
        #samples = tf.concat([context_input[:SAMPLE_SIZE,4:], context], axis=1) # compute batch of M samples

        # compute the memory and context
        #samples = tf.concat([memory_tile[:BATCH_SIZE], context], axis=1)


        #samples_plh = tf.placeholder(shape=[BATCH_SIZE, bar.get_shape()[1]], dtype=tf.float32, name="samples_plh")
        context_plh = tf.placeholder(shape=context.get_shape(), dtype=tf.float32, name="context_plh")
        # tf.cast(tf.expand_dims(tf.argmax(policy_batch, axis=1), axis=1), tf.float32)
        loss_input = tf.concat([state_batch_plh, terminate_batch_plh, reward_batch_plh, policy_batch, memory_tile_batch, policy_batch], axis=1)

        """ loss network operates on BATCH_SIZE buffer samples
        these samples include M {state, termination_signal pairs}
        TF computes the rest of the required components : f_context, mem, action, policy distribution
        """
        loss_scope = "loss"
        with tf.variable_scope(loss_scope):

            hidden = tf.layers.dense(loss_input, 16, activation=tf.nn.elu, kernel_initializer=initializer)
            loss  = tf.layers.dense(hidden, 1, activation=None, kernel_initializer=initializer, name="loss")

        loss_es_params = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=context_scope) + \
            tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=loss_scope)

        # same as memory as policy assign
        loss_es_assign_plhs = {}
        #loss_es_assign_ops = []
        for param in loss_es_params:
            param_value_plh = tf.placeholder(shape=param.get_shape(), dtype=tf.float32)
            assign_op = tf.assign(param, param_value_plh)
            loss_es_assign_plhs[param.name] = (param_value_plh, assign_op)
            #loss_es_assign_ops.append(assign_op)

        # require params be assigned before evaluating
        #with tf.control_dependencies(loss_es_assign_ops):
        #    loss = tf.identity(loss)

        # allows workers to access the loss params
        loss_es_params_dict = {}
        for param in loss_es_params:
            loss_es_params_dict[param.name] = param

        # policy gradient update given M (SAMPLE_SIZE) loss samples
        policy_gradients = {}
        learning_rate_policy_plh = tf.placeholder(shape=[1], dtype=tf.float32, name="learning_rate_policy_plh")
        for param in policy_params:
            policy_gradients[param.name] = tf.assign_add(param, -learning_rate_policy_plh * tf.clip_by_value(tf.reduce_mean(tf.gradients(loss, param), axis=0), -50, 50))

        # memory gradient update  given M (SAMPLE_SIZE) loss samples
        memory_gradients = {}
        learning_rate_memory_plh = tf.placeholder(shape=[1], dtype=tf.float32, name="learning_rate_memory_plh")
        for param in memory_params:
            memory_gradients[param.name] = tf.assign_add(param, -learning_rate_memory_plh * tf.clip_by_value(tf.reduce_mean(tf.gradients(loss, param), axis=0), -50, 50))

        # used to access param values
        #policy_params_dict = {}
        #for param in policy_params:
        #    policy_params_dict[param.name] = param

        # same as above
        #memory_params_dict = {}
        #for param in memory_params:
        #    memory_params_dict[param.name] = param
    return epg_graph,  loss_es_assign_plhs, loss_es_params_dict, policy_gradients, memory_gradients, loss, context


# Hyperparameters
NUM_STEPS = 64 * SAMPLE_SIZE # U
NUM_WORKERS = 64#256
TRAJ_SAMPLES = 256
GAMMA = 0.95
V = 16#64
SIGMA = 2.0
NUM_EPOCHS = 5#50
LEARNING_RATE_LOSS_ES = 0.002#7e-4
LEARNING_DECAY = 0.99
SIGMA_DECAY = 0.85
barrier = threading.Barrier(NUM_WORKERS)

def run_inner_loop(tid, barrier, loss_params, average_returns, run_sim=False):
    """ Inner Loop run for each worker
        Samples from MDP and follows a randomly initialized policy
        updates both memory and policy every M steps

        Args:
            lock: thread lock
            barrier: thread barrier
            loss_params: the loss params for this worker
            average_returns: average returns list
    """

    # buffers for state, term_signal, reward
    state_buffer = collections.deque([], maxlen=BUFFER_SIZE)
    term_buffer = collections.deque([], maxlen=BUFFER_SIZE)
    reward_buffer = collections.deque([], maxlen=BUFFER_SIZE)

    learning_rate_policy = 7e-4
    learning_rate_memory = 7e-4
    LEARNING_DECAY = 0.99


    #tf.reset_default_graph()
    env = gym.make('BipedalWalker-v2')
    epg_graph,  loss_es_assign_plhs, loss_es_params_dict, policy_gradients, memory_gradients, loss, context = build_graph()
    with epg_graph.as_default() as g:
        policy_sample = g.get_tensor_by_name("policy_sample:0")

        with tf.Session(graph=g) as sess:
            sess.run(tf.global_variables_initializer())
            # assign perturb phi (loss params)
            for param in loss_params.keys():
                sess.run(loss_es_assign_plhs[param][1], feed_dict={loss_es_assign_plhs[param][0]: loss_params[param]})
            if barrier is not None:
                barrier.wait()
            t = 0
            while t < NUM_STEPS:
                s = env.reset()
                done = False
                steps = 0
                while done != True:
                    steps += 1
                    a = sess.run(policy_sample, feed_dict={"state_sample_plh:0": np.array([s])})[0]
                    next_step, reward, done, info = env.step(a)
                    state_buffer.append(s)
                    term_buffer.append([done])
                    reward_buffer.append([reward])
                    s = next_step
                    t += 1
                    if t >= NUM_STEPS:
                        break
                    if done:
                        print("TID %d STEPS %d" %(tid, steps))

                    # once we have enoguh samples perform policy and mem param update
                    if  t == BUFFER_SIZE or (t >= BUFFER_SIZE and t % SAMPLE_SIZE == 0):
                        # context is computed over the whole buffer, it is replicated BATCH_SIZE times
                        context_values = sess.run(context, feed_dict={"state_plh:0": list(state_buffer), "terminate_plh:0": list(term_buffer), "reward_plh:0": list(reward_buffer)})

                        # we randomly sample batches for param update
                        joint = list(zip(list(state_buffer)[-SAMPLE_SIZE:], list(term_buffer)[-SAMPLE_SIZE:], list(reward_buffer)[-SAMPLE_SIZE:]))
                        random.shuffle(joint)
                        random.shuffle(joint)
                        random.shuffle(joint)
                        random.shuffle(joint)
                        state_batch, term_batch, reward_batch = zip(*joint)

                        num_batches = SAMPLE_SIZE % BATCH_SIZE
                        for i in range(num_batches):

                            state_mb = state_batch[BATCH_SIZE * i:BATCH_SIZE * (i + 1)]
                            term_mb = term_batch[BATCH_SIZE * i:BATCH_SIZE * (i + 1)]
                            reward_mb = reward_batch[BATCH_SIZE * i:BATCH_SIZE * (i + 1)]

                            # policy and mem gradient update
                            #if run_sim:
                            sess.run(policy_gradients, feed_dict={"context_plh:0": context_values, "state_batch_plh:0": state_mb,
                                "terminate_batch_plh:0": term_mb, "reward_batch_plh:0": reward_mb, "learning_rate_policy_plh:0": [learning_rate_policy]})
                            sess.run(memory_gradients, feed_dict={"context_plh:0": context_values, "state_batch_plh:0": state_mb,
                                "terminate_batch_plh:0": term_mb, "reward_batch_plh:0": reward_mb, "learning_rate_memory_plh:0": [learning_rate_memory]})

                            learning_rate_policy *= LEARNING_DECAY
                            learning_rate_memory *= LEARNING_DECAY


            """ Now we use learned policy to sample some trajectories,
            and compute the average return from all trajectories
            """
            returns = []
            for _ in range(TRAJ_SAMPLES):
                s = env.reset()
                done = False
                R = 0
                rewards = []
                steps = 0
                while done != True:
                    a = sess.run(policy_sample, feed_dict={"state_sample_plh:0": np.array([s])})[0]
                    s, reward, done, info = env.step(a)
                    if run_sim:
                        env.render()
                    rewards.append(reward)
                    steps += 1
                print("TID %d TRAJ STEPS %d" %(tid, steps))
                for i in reversed(range(len(rewards))):
                    R = rewards[i] + GAMMA * R
                returns.append(R)
            if average_returns is not None:
                average_returns[tid] = sum(returns) / TRAJ_SAMPLES


def run_outer_loop():
    """ Runs the outer loop of the algorithm
    Spawns the workers and performs updates to phi (the ES loss params)
    """
    global LEARNING_RATE_LOSS_ES, LEARNING_DECAY, SIGMA

    epg_graph, _, loss_es_params_dict, _, _, _, _ = build_graph()
    with epg_graph.as_default():
        # initialize phi (the loss ES params)
        with tf.Session() as sess:
            sess.run(tf.variables_initializer(loss_es_params_dict.values()))
            loss_es_params_values = sess.run(loss_es_params_dict)
            return loss_es_params_values
            for e in range(NUM_EPOCHS):
                # construct perturbed phi (loss) params
                epsilon_vectors = []
                normal_vectors = []
                for i in range(V):
                    param_pertubed = {}
                    normal_vectors_dict = {}
                    for param in loss_es_params_values.keys():
                        param_shape = loss_es_params_values[param].shape#map(lambda x: int(x), loss_es_params_dict[param].get_shape())
                        #num_params = reduce(operator.mul, param_shape)

                        normal = tf.random_normal(shape=param_shape)
                        normal_vectors_dict[param] = sess.run(normal)
                        param_pertubed[param] = loss_es_params_values[param] + SIGMA * normal_vectors_dict[param]#np.reshape(np.random.multivariate_normal([0] * num_params, np.eye(num_params, num_params)), param_shape)
                    epsilon_vectors.append(param_pertubed)
                    normal_vectors.append(normal_vectors_dict)

                threads = []
                average_returns = [None] * NUM_WORKERS
                for tid in range(NUM_WORKERS):
                    threads.append(threading.Thread(target=run_inner_loop, args=(tid, barrier, epsilon_vectors[math.floor(tid * V/NUM_WORKERS)], average_returns)))

                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

                # compute ES gradients and update
                for param in loss_es_params_values.keys():
                    F = []
                    num_workers_per_set = int(NUM_WORKERS / V) # guarantee divis
                    for i in range(num_workers_per_set):
                        F.append(sum(average_returns[num_workers_per_set *i: num_workers_per_set*(i+1)])/(num_workers_per_set) * normal_vectors[i][param])
                    grad = sum(F)/(SIGMA * V)
                    loss_es_params_values[param] += (LEARNING_RATE_LOSS_ES * grad)
                LEARNING_RATE_LOSS_ES *= LEARNING_DECAY
                SIGMA *= SIGMA_DECAY

                print("EPOCH %d " % e, average_returns)
                print("AVERAGE %f" % (sum(average_returns)/ NUM_WORKERS))
                run_inner_loop(0,  None, loss_es_params_values, None, run_sim=True)
        return loss_es_params_values




loss_params = run_outer_loop()
print("DONE")
run_inner_loop(0,  None, loss_params, None, run_sim=True)