#!/bin/bash -e
#SBATCH --partition=hgx
#SBATCH --time=00-00:05:00
#SBATCH --gpus-per-node=A100:4
#SBATCH --cpus-per-task=2
#SBATCH --mem=16GB
#SBATCH --output=logs/%j_%x.out
#SBATCH --error=logs/%j_%x.out

# load modules
module purge
module load CUDA/11.6.2
module load Miniconda3/22.11.1-1
source $(conda info --base)/etc/profile.d/conda.sh
export PYTHONNOUSERSITE=1

# display information about the available GPUs
nvidia-smi

# check the value of the CUDA_VISIBLE_DEVICES variable
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"

# activate conda environment
conda deactivate
conda activate ./venv
which python

# optional, used to peek under NCCL's hood
export NCCL_DEBUG=INFO 

# start training script
# TODO pass the number of available CPUs from Slurm
torchrun \
    --standalone \
    --nnodes=1 \
    --nproc_per_node=${SLURM_GPUS_PER_NODE#*:} \
    train.py
