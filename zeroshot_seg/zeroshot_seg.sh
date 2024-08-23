#!/bin/bash

# Path to dataset
DATA=/data/ziqi/shapenetpart

# Classes: [airplane, bag, cap, car, chair, earphone, guitar, knife, lamp, laptop, motorbike, mug, pistol, rocket, skateboard, table]
CLASS=Window

export CUDA_VISIBLE_DEVICES=3
python main.py \
--modelname ViT-B/16 \
--classchoice ${CLASS} \
--datasetpath ${DATA}
