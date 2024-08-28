#!/bin/bash

# Path to dataset
DATA=/data/ziqi/shapenetpart

# Classes: [airplane, bag, cap, car, chair, earphone, guitar, knife, lamp, laptop, motorbike, mug, pistol, rocket, skateboard, table]

export CUDA_VISIBLE_DEVICES=6
python main.py \
--modelname ViT-B/16 \
--datasetpath ${DATA}
