import os
import json
import tensorflow as tf
import numpy as np
from experiment_utils.run_sweep import run_sweep
from maml_zoo.utils.utils import set_seed, ClassEncoder
from maml_zoo.baselines.linear_baseline import LinearTimeBaseline, LinearFeatureBaseline
from maml_zoo.envs.half_cheetah_rand_direc import HalfCheetahRandDirecEnv
from maml_zoo.envs.ant_rand_direc import AntRandDirecEnv
from maml_zoo.envs.half_cheetah_rand_vel import HalfCheetahRandVelEnv
from maml_zoo.envs.normalized_env import normalize
from experiments.gradient_variance.dice_maml_extract_grads import DICEMAML
from experiments.gradient_variance.vpg_maml_extract_grads import VPGMAML
from experiments.gradient_variance.meta_trainer_gradient_variance import TrainerGradientStd
from maml_zoo.samplers.maml_sampler import MAMLSampler
from maml_zoo.samplers import DiceMAMLSampleProcessor, MAMLSampleProcessor
from maml_zoo.policies.meta_gaussian_mlp_policy import MetaGaussianMLPPolicy
from maml_zoo.logger import logger

INSTANCE_TYPE = 'c4.2xlarge'
EXP_NAME = 'gradient_std'

def run_experiment(**kwargs):
    exp_dir = os.getcwd() + '/data/' + EXP_NAME
    logger.configure(dir=exp_dir, format_strs=['stdout', 'log', 'csv'], snapshot_mode='last_gap', snapshot_gap=50)
    json.dump(kwargs, open(exp_dir + '/params.json', 'w'), indent=2, sort_keys=True, cls=ClassEncoder)

    # Instantiate classes
    set_seed(kwargs['seed'])

    env = normalize(kwargs['env']()) # Wrappers?

    policy = MetaGaussianMLPPolicy(
        name="meta-policy",
        obs_dim=np.prod(env.observation_space.shape),
        action_dim=np.prod(env.action_space.shape),
        meta_batch_size=kwargs['meta_batch_size'],
        hidden_sizes=kwargs['hidden_sizes'],
        learn_std=kwargs['learn_std'],
        hidden_nonlinearity=kwargs['hidden_nonlinearity'],
        output_nonlinearity=kwargs['output_nonlinearity'],
    )

    # Load policy here

    sampler = MAMLSampler(
        env=env,
        policy=policy,
        rollouts_per_meta_task=kwargs['rollouts_per_meta_task'],
        meta_batch_size=kwargs['meta_batch_size'],
        max_path_length=kwargs['max_path_length'],
        parallel=kwargs['parallel'],
        envs_per_task=int(kwargs['rollouts_per_meta_task']/4)
    )

    if kwargs['algo'] == 'DICE':
        sample_processor = DiceMAMLSampleProcessor(
            baseline=LinearTimeBaseline(),
            max_path_length=kwargs['max_path_length'],
            discount=kwargs['discount'],
            normalize_adv=kwargs['normalize_adv'],
            positive_adv=kwargs['positive_adv'],
            normalize_by_path_length=kwargs['normalize_by_path_length']
        )

        algo = DICEMAML(
            policy=policy,
            max_path_length=kwargs['max_path_length'],
            meta_batch_size=kwargs['meta_batch_size'],
            num_inner_grad_steps=kwargs['num_inner_grad_steps'],
            inner_lr=kwargs['inner_lr'],
            learning_rate=kwargs['learning_rate']
        )
    elif kwargs['algo'] == 'VPG':
        sample_processor = MAMLSampleProcessor(
            baseline=LinearFeatureBaseline(),
            discount=kwargs['discount'],
            normalize_adv=kwargs['normalize_adv'],
            positive_adv=kwargs['positive_adv'],
        )

        algo = VPGMAML(
            policy=policy,
            meta_batch_size=kwargs['meta_batch_size'],
            num_inner_grad_steps=kwargs['num_inner_grad_steps'],
            inner_type='likelihood_ratio',
            inner_lr=kwargs['inner_lr'],
            learning_rate=kwargs['learning_rate']
        )

    trainer = TrainerGradientStd(
        algo=algo,
        policy=policy,
        env=env,
        sampler=sampler,
        sample_processor=sample_processor,
        n_itr=kwargs['n_itr'],
        num_inner_grad_steps=kwargs['num_inner_grad_steps'],
    )

    trainer.train()

if __name__ == '__main__':    

    sweep_params = {
        'seed': [1, 2, 3],

        'algo': ['VPG', 'DICE'],

        'sampling_rounds': [10],

        #'baseline': [LinearTimeBaseline, LinearFeatureBaseline],

        'env': [HalfCheetahRandDirecEnv],

        'rollouts_per_meta_task': [40],
        'max_path_length': [100],
        'parallel': [True],

        'discount': [0.99],
        'normalize_adv': [True],
        'positive_adv': [False],
        'normalize_by_path_length': [True, False],

        'hidden_sizes': [(64, 64)],
        'learn_std': [True],
        'hidden_nonlinearity': [tf.tanh],
        'output_nonlinearity': [None],

        'inner_lr': [0.1],
        'learning_rate': [1e-3],

        'n_itr': [501],
        'meta_batch_size': [20],
        'num_inner_grad_steps': [1],
        'scope': [None],
    }
        
    run_sweep(run_experiment, sweep_params, EXP_NAME, INSTANCE_TYPE)