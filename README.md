# CS330 Project: Clustered Meta Learning


This project aims to improve the performance of Model-Agnostic Meta Learning (MAML) by having multiple meta-parameters that enable the algorithm to understand the relations between various tasks. Read the report [here](report.pdf)

To run the algorithm, select the desired configuration in `run_scripts/maml_run_mujoco.py` and run

```python run_scripts/maml_run_mujoco.py```

To load a model change the loading flag in `meta_policy_search/meta_trainer.py` and provide the checkpoint directory.


## Acknowledgements
This repository is a fork of a repository by `zhanpenghe` and we thank Tianhe Yu for helping us with structuring the code for our experiments.
