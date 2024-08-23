import os
import torch
import random
import warnings
import argparse
from tqdm import tqdm
from clip import clip
from torch.utils.data import DataLoader
warnings.filterwarnings("ignore")

from best_param import *
from data import ShapeNetPart, PartNetMobility, Objaverse
from realistic_projection import Realistic_Projection
from post_search import textual_encoder, eval_sample_objaverse
import time
import numpy as np

PC_NUM = 2048

class Extractor(torch.nn.Module):
    def __init__(self, model):
        super(Extractor, self).__init__()

        self.model = model
        self.pc_views = Realistic_Projection()
        self.get_img = self.pc_views.get_img
        
    def mv_proj(self, pc):
        img, is_seen, point_loc_in_img = self.get_img(pc)
        img = img[:, :, 20:204, 20:204]
        point_loc_in_img = torch.ceil((point_loc_in_img - 20) * 224. / 184.)
        img = torch.nn.functional.interpolate(img, size=(224, 224), mode='bilinear', align_corners=True)
        return img, is_seen, point_loc_in_img

    def forward(self, pc):
        img, is_seen, point_loc_in_img = self.mv_proj(pc)
        _, x = self.model.encode_image(img)
        x = x / x.norm(dim=-1, keepdim=True)
        
        B, L, C = x.shape
        x = x.reshape(B, 14, 14, C).permute(0,3,1,2)
        return is_seen, point_loc_in_img, x


def eval_objs(model_name, partition, device):
    model, _ = clip.load(model_name, device=device)
    model.to(device)

    segmentor = Extractor(model)
    segmentor = segmentor.to(device)
    segmentor.eval()

    test_loader = DataLoader(Objaverse(num_points=PC_NUM, partition=partition), batch_size=1, shuffle=False, drop_last=False)
    acc_store = []
    iou_store = []
    cat_acc = {}
    cat_iou = {}
    for data in tqdm(test_loader):
        #eval shapenet-part
        pc, label, label_texts_ordered, cat = data # label_texts_ordered correspond to labels 0->n-1
        pc, label = pc.cuda(), label.cuda()
        with torch.no_grad():
            is_seen, point_loc_in_img, feat = segmentor(pc)
            # encoding textual features
            label_texts_ordered.append("other")
            clip_model, _ = clip.load(model_name)
            clip_model.eval()
            text_feat, prompts = textual_encoder(clip_model, "", label_texts_ordered)
            text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
            acc, iou = eval_sample_objaverse(feat, label, is_seen, point_loc_in_img, text_feat, len(label_texts_ordered)-1)
        acc_store.append(acc.item())
        iou_store.append(iou.item())
        if cat not in cat_acc:
            cat_acc[cat] = [acc.item()]
        else:
            cat_acc[cat].append(acc.item())

        if cat not in cat_iou:
            cat_iou[cat] = [iou.item()]
        else:
            cat_iou[cat].append(iou.item())

    mean_acc = np.mean(acc_store)
    mean_iou = np.mean(iou_store)
    mean_cat_accs = []
    mean_cat_ious = []
    for cat in cat_acc:
        mean_cat_accs.append(np.mean(cat_acc[cat]))
    for cat in cat_iou:
        mean_cat_ious.append(np.mean(cat_iou[cat]))
    cat_mean_acc = np.mean(mean_cat_accs)
    cat_mean_iou = np.mean(mean_cat_ious)
    print(f"instance mean acc: {mean_acc}")
    print(f"instance mean iou: {mean_iou}")
    print(f"category mean acc: {cat_mean_acc}")
    print(f"category mean iou: {cat_mean_iou}")
    


def main(args):
    random.seed(0)
    device = "cuda:0"
    model_name = args.modelname

    # extract and save feature maps, labels, point locations
    eval_objs(model_name, "unseen", device)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--modelname', default='ViT-B/16')
    args = parser.parse_args()
    stime = time.time()
    main(args)
    etime = time.time()
    print(etime-stime)
