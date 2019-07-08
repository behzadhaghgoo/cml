import argparse
import datetime
import os
import json
import pathlib
import sys

import dateutil.tz
import joblib
import numpy as np
import tensorflow as tf

from maml_zoo.baselines.linear_baseline import LinearFeatureBaseline
from maml_zoo.envs.multitask_env import MultiClassMultiTaskEnv
from maml_zoo.envs.rl2_env import rl2env
from maml_zoo.algos.ppo import PPO
from maml_zoo.trainer import Trainer
from maml_zoo.samplers.maml_sampler import MAMLSampler
from maml_zoo.samplers.rl2_sample_processor import RL2SampleProcessor
from maml_zoo.policies.gaussian_rnn_policy import GaussianRNNPolicy
from maml_zoo.logger import logger


def rl2_eval(experiment, config, sess, start_itr, all_params):

    from medium_env_list import TEST_DICT, MEDIUM_MODE_ARGS_KWARGS

    env = experiment['env']

    print('Environments: {}'.format(env._wrapped_env._task_names))

    baseline = LinearFeatureBaseline()
    policy = experiment['policy']

    sampler = MAMLSampler(
        env=env,
        policy=policy,
        rollouts_per_meta_task=config['rollouts_per_meta_task'],  # This batch_size is confusing
        meta_batch_size=config['meta_batch_size'],
        max_path_length=config['max_path_length'],
        parallel=config['parallel'],
        envs_per_task=config['envs_per_task']
    )

    sample_processor = RL2SampleProcessor(
        baseline=baseline,
        discount=config['discount'],
        gae_lambda=config['gae_lambda'],
        normalize_adv=config['normalize_adv'],
        positive_adv=config['positive_adv'],
    )

    algo = PPO(
        policy=policy,
        learning_rate=0.,
        max_epochs=config['max_epochs'],
    )

    trainer = Trainer(
        algo=algo,
        policy=policy,
        env=env,
        sampler=sampler,
        sample_processor=sample_processor,
        n_itr=start_itr+1,
        sess=sess,
        start_itr=start_itr,
    )

    trainer.eval_params(all_params)
    sys.exit(0)

if __name__=="__main__":
    parser = argparse.ArgumentParser(description='Play a pickled policy.')
    parser.add_argument('variant_index', metavar='variant_index', type=int,
                    help='The index of variants to use for experiment')
    parser.add_argument('--dir', metavar='dir', type=str,
                    help='The path of the folder that contains pkl files',
                    default=None, required=False)
    parser.add_argument('--pkl', metavar='pkl', type=str,
                    help='The path of the pkl file',
                    default=None, required=False)
    parser.add_argument('--config', metavar='config', type=str,
                    help='The path to the config file',
                    default=None, required=False)
    parser.add_argument('--itr', metavar='itr', type=int,
                    help='The start itr of the resuming experiment',
                    default=0, required=False)
    args = parser.parse_args()

    now = datetime.datetime.now(dateutil.tz.tzlocal())
    timestamp = now.strftime('%Y_%m_%d_%H_%M_%S')
    idx = args.variant_index
    pkl = args.pkl
    folder = args.dir
    config_file = args.config
    itr = args.itr

    from os import listdir
    from os.path import isfile
    import os.path
    pkls = [file for file in listdir(folder) if '.pkl' in file]

    if not config_file:
        config_file = './corl/rl2/configs/medium_mode_config{}.json'.format(idx)

    if pkl:
        raise NotImplementedError
        with tf.Session() as sess:
            with open(pkl, 'rb') as file:
                experiment = joblib.load(file)
            logger.configure(dir='./data/rl2/eval_{}'.format(exp_name), format_strs=['stdout', 'log', 'csv', 'json', 'tensorboard'],
                     snapshot_mode='all',)
            config = json.load(open(config_file, 'r'))
            json.dump(config, open('./data/rl2/eval_{}/params.json'.format(exp_name), 'w'))
            rl2_eval(experiment, config, sess, pkl_itr, pkl)
    elif folder:
        exp_path = pathlib.Path(folder)
        exp_name = exp_path.parts[-1]
        eval_path = pathlib.Path('./data/rl2/eval_{}'.format(exp_name))
        output_path = eval_path / 'meta_train'
        all_params = joblib.load(eval_path / 'all_params.pkl')
        for p in pkls:
            pkl_itr = int(p.split('_')[-1].split('.')[0])
            with tf.Graph().as_default():
                with tf.Session() as sess:
                    with open(os.path.join(folder, p), 'rb') as file:
                        experiment = joblib.load(file)
                    logger.configure(dir=str(output_path), format_strs=['stdout', 'log', 'csv', 'json', 'tensorboard'],
                             snapshot_mode='all',)
                    config = json.load(open(config_file, 'r'))
                    json.dump(config, open(output_path / 'params.json', 'w'))
                    rl2_eval(experiment, config, sess, pkl_itr, all_params)
    else:
        print('Please provide a pkl file')
