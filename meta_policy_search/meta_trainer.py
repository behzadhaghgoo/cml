import tensorflow as tf
import numpy as np
import time
from meta_policy_search.utils import logger
import numpy as np

from collections import OrderedDict


class Timer():
    """Timer Class."""

    def __init__(self):
        """Initialize timer and lap counter."""
        self.time = time.time()
        self.counter = 0

    def time_elapsed(self):
        """
        Return time elapsed since last interaction with the timer
        (Either starting it or getting time elapsed).
        """
        self.counter += 1
        delta_t = time.time() - self.time
        print(self.counter, delta_t)
        self.time = time.time()
        return delta_t

    def start(self):
        """Restart timer"""
        self.time = time.time()
        self.counter = 0


class Trainer(object):
    """
    Performs steps of meta-policy search.

     Pseudocode::

            for iter in n_iter:
                sample tasks
                for task in tasks:
                    for adapt_step in num_inner_grad_steps
                        sample trajectories with policy
                        perform update/adaptation step
                    sample trajectories with post-update policy
                perform meta-policy gradient step(s)

    Args:
        algo (Algo) :
        env (Env) :
        sampler (Sampler) :
        sample_processor (SampleProcessor) :
        baseline (Baseline) :
        policy (Policy) :
        n_itr (int) : Number of iterations to train for
        start_itr (int) : Number of iterations policy has already trained for, if reloading
        num_inner_grad_steps (int) : Number of inner steps per maml iteration
        sess (tf.Session) : current tf session (if we loaded policy, for example)
    """

    def __init__(
            self,
            algo,
            envs,
            env_ids,
            samplers,
            sample_processor,
            policy,
            n_itr,
            start_itr=0,
            num_inner_grad_steps=1,
            sess=None,
    ):
        self.algo = algo
        self.envs = envs
        self.env_ids = env_ids
        self.samplers = samplers
        self.sample_processor = sample_processor
        self.baseline = sample_processor.baseline
        self.policy = policy
        self.n_itr = n_itr
        self.start_itr = start_itr
        self.num_inner_grad_steps = num_inner_grad_steps
        self.saver = tf.train.Saver()
        if sess is None:
            sess = tf.Session()
        self.sess = sess

    def train(self):
        """
        Trains policy on env using algo

        Pseudocode::

            for itr in n_itr:
                for step in num_inner_grad_steps:
                    sampler.sample()
                    algo.compute_updated_dists()
                algo.optimize_policy()
                sampler.update_goals()
        """
        with self.sess.as_default() as sess:

            # initialize uninitialized vars  (only initialize vars that were not loaded)
            uninit_vars = [var for var in tf.global_variables(
            ) if not sess.run(tf.is_variable_initialized(var))]
            sess.run(tf.variables_initializer(uninit_vars))

            start_time = time.time()
            for itr in range(self.start_itr, self.n_itr):
                itr_start_time = time.time()
                logger.log(
                    "\n ---------------- Iteration %d ----------------" % itr)
                logger.log(
                    "Sampling set of tasks/goals for this meta-batch...")

                for sampler in self.samplers:
                    sampler.update_tasks()
                self.policy.switch_to_pre_update()  # Switch to pre-update policy

                all_samples_data, all_paths = [], []
                list_sampling_time, list_inner_step_time, list_outer_step_time, list_proc_samples_time = [], [], [], []
                start_total_inner_time = time.time()
                for step in range(self.num_inner_grad_steps+1):
                    logger.log('** Step ' + str(step) + ' **')

                    """ -------------------- Sampling --------------------------"""

                    logger.log("Obtaining samples...")
                    time_env_sampling_start = time.time()

                    sampler = np.random.choice(self.samplers, p=[0.5, 0.5])
                    paths = sampler.obtain_samples(
                        log=True, log_prefix='Step_%d-' % step)
                    list_sampling_time.append(
                        time.time() - time_env_sampling_start)
                    all_paths.append(paths)

                    """ ----------------- Processing Samples ---------------------"""

                    logger.log("Processing samples...")
                    time_proc_samples_start = time.time()
                    samples_data = self.sample_processor.process_samples(
                        paths, log='all', log_prefix='Step_%d-' % step)
                    all_samples_data.append(samples_data)
                    list_proc_samples_time.append(
                        time.time() - time_proc_samples_start)

                    self.log_diagnostics(
                        sum(list(paths.values()), []), prefix='Step_%d-' % step)

                    """ ------------------- Inner Policy Update --------------------"""

                    time_inner_step_start = time.time()
                    if step < self.num_inner_grad_steps:
                        logger.log("Computing inner policy updates...")
                        self.algo._adapt(samples_data)
                    # train_writer = tf.summary.FileWriter('/home/ignasi/Desktop/meta_policy_search_graph',
                    #                                      sess.graph)
                    list_inner_step_time.append(
                        time.time() - time_inner_step_start)
                total_inner_time = time.time() - start_total_inner_time

                time_maml_opt_start = time.time()
                """ ------------------ Outer Policy Update ---------------------"""

                logger.log("Optimizing policy...")
                # This needs to take all samples_data so that it can construct graph for meta-optimization.
                time_outer_step_start = time.time()
                self.algo.optimize_policy(all_samples_data)

                """ ------------------- Logging Stuff --------------------------"""
                logger.logkv('Itr', itr)
                logger.logkv('n_timesteps', [
                             sampler.total_timesteps_sampled for sampler in self.samplers])

                logger.logkv('Time-OuterStep', time.time() -
                             time_outer_step_start)
                logger.logkv('Time-TotalInner', total_inner_time)
                logger.logkv('Time-InnerStep', np.sum(list_inner_step_time))
                logger.logkv('Time-SampleProc', np.sum(list_proc_samples_time))
                logger.logkv('Time-Sampling', np.sum(list_sampling_time))

                logger.logkv('Time', time.time() - start_time)
                logger.logkv('ItrTime', time.time() - itr_start_time)
                logger.logkv('Time-MAMLSteps', time.time() -
                             time_maml_opt_start)

                logger.log("Saving snapshot...")
                params = self.get_itr_snapshot(itr)
                logger.save_itr_params(itr, params)
                logger.log("Saved")

                logger.dumpkvs()

        logger.log("Training finished")
        self.saver.save(sess, '{}'.format(self.env_ids))
        self.sess.close()

    def get_itr_snapshot(self, itr):
        """
        Gets the current policy and env for storage
        """
        return dict(itr=itr, policy=self.policy, env=self.envs, baseline=self.baseline)

    def log_diagnostics(self, paths, prefix):
        # TODO: we aren't using it so far
        #self.envs.log_diagnostics(paths, prefix)
        self.policy.log_diagnostics(paths, prefix)
        self.baseline.log_diagnostics(paths, prefix)


class KAML_Trainer(object):
    """
    Performs steps of meta-policy search.

     Pseudocode::

            for iter in n_iter:
                sample tasks
                for task in tasks:
                    for adapt_step in num_inner_grad_steps
                        sample trajectories with policy
                        perform update/adaptation step
                    sample trajectories with post-update policy
                perform meta-policy gradient step(s)

    Args:
        algo (Algo) :
        env (Env) :
        sampler (Sampler) :
        sample_processor (SampleProcessor) :
        baseline (Baseline) :
        policy (Policy) :
        n_itr (int) : Number of iterations to train for
        start_itr (int) : Number of iterations policy has already trained for, if reloading
        num_inner_grad_steps (int) : Number of inner steps per maml iteration
        sess (tf.Session) : current tf session (if we loaded policy, for example)
    """

    def __init__(
            self,
            algos,
            envs,
            samplers,
            sample_processor,
            policies,
            n_itr,
            start_itr=0,
            num_inner_grad_steps=1,
            sess=None,
            theta_count=2,
            probs=[0.5, 0.5]
    ):
        print("initialize KAML trainer")
        self.algos = algos
        self.theta_count = theta_count

        self.envs = envs
        self.samplers = samplers
        self.sample_processor = sample_processor
        self.baseline = sample_processor.baseline
        self.policies = policies
        self.n_itr = n_itr
        self.start_itr = start_itr
        self.num_inner_grad_steps = num_inner_grad_steps
        self.probs = probs

        assert len(samplers) == len(
            probs), "len(samplers) = {} != {} = len(probs)".format(len(samplers), len(probs))

        if sess is None:
            sess = tf.Session()
        self.sess = sess

        self.timer = Timer()

    def train(self):
        """
        Trains policy on env using algo

        Pseudocode::

            for itr in n_itr:
                for step in num_inner_grad_steps:
                    sampler.sample()
                    algo.compute_updated_dists()
                algo.optimize_policy()
                sampler.update_goals()
        """

        self.timer.start()

        with self.sess.as_default() as sess:

            # initialize uninitialized vars  (only initialize vars that were not loaded)
            uninit_vars = [var for var in tf.global_variables(
            ) if not sess.run(tf.is_variable_initialized(var))]
            sess.run(tf.variables_initializer(uninit_vars))

            start_time = time.time()
            for itr in range(self.start_itr, self.n_itr):

                print("\n\n\n\n\n")
                self.timer.time_elapsed()
                print("\n\n\n\n\n")

                itr_start_time = time.time()
                logger.log(
                    "\n ---------------- Iteration %d ----------------" % itr)
                logger.log(
                    "Sampling set of tasks/goals for this meta-batch...")

                # Here, we're sampling meta_batch_size / |envs| # of tasks for each environment
                for sampler in self.samplers:
                    sampler.update_tasks()

                # For each theta in thetas, we obtain trajectories from the same tasks from both environments
                for algo in self.algos[:self.theta_count]:
                    policy = algo.policy
                    policy.switch_to_pre_update()  # Switch to pre-update policy

                    all_samples_data, all_paths, algo_all_samples = [], [], []
                    list_sampling_time, list_inner_step_time, list_outer_step_time, list_proc_samples_time = [], [], [], []
                    start_total_inner_time = time.time()
                    inner_loop_losses = []
                    for step in range(self.num_inner_grad_steps+1):
                        logger.log('** Step ' + str(step) + ' **')

                        """ -------------------- Sampling --------------------------"""

                        logger.log("Obtaining samples...")
                        time_env_sampling_start = time.time()

                        # Meta-sampler's obtain_samples function now takes as input policy since we need trajectories for each policy
                        initial_paths = [sampler.obtain_samples(
                            policy=policy, log=True, log_prefix='Step_%d-' % step) for sampler in self.samplers]

                        true_indices = []
                        paths = OrderedDict()
                        # len(self.envs) == len(initial_paths)
                        # , Paths in enumerate(zip(*initial_paths)):
                        for i in range(len(initial_paths[0])):
                            index = np.random.choice(
                                list(range(len(initial_paths))), p=self.probs)
                            paths[i] = initial_paths[index][i]
                            true_indices.append(index)

                        # list of 0's and 1's indicating which env
                        true_indices = np.array(true_indices)
                        list_sampling_time.append(
                            time.time() - time_env_sampling_start)
                        # (number of inner updates, meta_batch_size)
                        all_paths.append(paths)

                        """ ----------------- Processing Samples ---------------------"""

                        logger.log("Processing samples...")
                        time_proc_samples_start = time.time()
                        samples_data = self.sample_processor.process_samples(
                            paths, log='all', log_prefix='Step_%d-' % step)
                        # (number of inner updates, meta_batch_size)
                        all_samples_data.append(samples_data)

                        # DEBUG
                        # print("length of all_samples_data should be 40: {}".format(len(all_samples_data)))
                        # print("all_samples_data[0] shape: {}".format(all_samples_data[0].shape))

                        list_proc_samples_time.append(
                            time.time() - time_proc_samples_start)

                        self.log_diagnostics(
                            sum(list(paths.values()), []), prefix='Step_%d-' % step)

                        """ ------------------- Inner Policy Update --------------------"""
                        if step < self.num_inner_grad_steps:
                            inner_loop_losses = []

                    # for algo in self.algos[:self.theta_count]: already looping over algos now so we don't need this
                        time_inner_step_start = time.time()
                        if step < self.num_inner_grad_steps:
                            logger.log("Computing inner policy updates...")
                            loss_list = algo._adapt(samples_data)
                            inner_loop_losses.append(loss_list)

                        indices = np.argmin(inner_loop_losses, axis=0)
                        pred_indices = np.array(indices)

                        print("Clustering Score = {}".format(
                            np.mean(np.abs(true_indices - pred_indices))))

#                     algo_batches = [[] for _ in range(self.theta_count)]
#                     for i in range(len(samples_data)):
#                         index = indices[i]
#                         algo_batches[index].append((i, samples_data[i]))

#                     algo_all_samples.append(algo_batches)

                        list_inner_step_time.append(
                            time.time() - time_inner_step_start)
                    total_inner_time = time.time() - start_total_inner_time

                    time_maml_opt_start = time.time()
                    """ ------------------ Outer Policy Update ---------------------"""

                    logger.log("Optimizing policy...")
                    # This needs to take all samples_data so that it can construct graph for meta-optimization.
                    time_outer_step_start = time.time()
                    # all_samples_index_data = [algo_batches[index]
                    #                          for algo_batches in algo_all_samples]
                    algo.optimize_policy(all_samples_data)

                """ ------------------- Logging Stuff --------------------------"""
                logger.logkv('Itr', itr)
                logger.logkv('n_timesteps', [
                             sampler.total_timesteps_sampled for sampler in self.samplers])

                logger.logkv('Time-OuterStep', time.time() -
                             time_outer_step_start)
                logger.logkv('Time-TotalInner', total_inner_time)
                logger.logkv('Time-InnerStep', np.sum(list_inner_step_time))
                logger.logkv('Time-SampleProc', np.sum(list_proc_samples_time))
                logger.logkv('Time-Sampling', np.sum(list_sampling_time))

                logger.logkv('Time', time.time() - start_time)
                logger.logkv('ItrTime', time.time() - itr_start_time)
                logger.logkv('Time-MAMLSteps', time.time() -
                             time_maml_opt_start)

                logger.log("Saving snapshot...")
                params = self.get_itr_snapshot(itr)
                logger.save_itr_params(itr, params)
                logger.log("Saved")

                logger.dumpkvs()

        logger.log("Training finished")
        self.sess.close()

    def get_itr_snapshot(self, itr):
        """
        Gets the current policy and env for storage
        """
        return dict(itr=itr, policies=self.policies, env=self.envs, baseline=self.baseline)

    def log_diagnostics(self, paths, prefix):
        # TODO: we aren't using it so far
        #self.envs.log_diagnostics(paths, prefix)
        # self.poli.log_diagnostics(paths, prefix)
        self.baseline.log_diagnostics(paths, prefix)
