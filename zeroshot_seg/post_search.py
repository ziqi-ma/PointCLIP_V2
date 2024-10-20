import json
import clip
import torch
import numpy as np
import os.path as osp
import scipy.io as sio
from best_param import *
import torch.nn.functional as F
from data import id2cat, cat2part
from util import calculate_shape_IoU
import open3d as o3d
import plotly.graph_objects as go

#PC_NUM = 2048 this changes for other datasets

feat_dims = {'ViT-B/16':512, 'ViT-B/32':512, 'RN50':1024, 'RN101':512}
cat2id = {'airplane': 0, 'bag': 1, 'cap': 2, 'car': 3, 'chair': 4, 
            'earphone': 5, 'guitar': 6, 'knife': 7, 'lamp': 8, 'laptop': 9, 
            'motorbike': 10, 'mug': 11, 'pistol': 12, 'rocket': 13, 'skateboard': 14, 'table': 15,
            # partnet-M
            'Bottle':16, 'Box':17, 'Bucket':18, 'Camera':19, 'Cart':20, 'Chair':21, 'Clock':22,
            "CoffeeMachine": 23, 'Dishwasher': 24, 'Dispenser': 25, "Display": 26, 'Eyeglasses': 27,
            'Faucet': 28, "FoldingChair": 29, "Globe": 30, "Kettle":31, "Keyboard": 32, "KitchenPot": 33,
            "Knife": 34, "Lamp": 35, "Laptop": 36, "Lighter": 37, "Microwave": 38, "Mouse": 39, "Oven": 40,
            "Pen": 41, "Phone": 42, "Pliers": 43, "Printer": 44, "Refrigerator": 45, "Remote": 46,
            "Safe": 47, "Scissors": 48, "Stapler": 49, "StorageFurniture": 50, "Suitcase": 51,
            "Switch": 52, "Table": 53, "Toaster": 54, "Toilet": 55, "TrashCan": 56, "USB": 57,
            "WashingMachine": 58, "Window": 59, "Door": 60}
seg_num = [4, 2, 2, 4, 4, 3, 3, 2, 4, 2, 6, 2, 3, 3, 3, 3, # shapenet-part
           1, 1, 1, 2, 1, 5, 1, 4, 2, 2, 3, 2, 2, 1, 1, 3, 2, 2, 1,
           4, 5, 3, 4, 3, 2, 2, 2, 1, 1, 2, 1, 3, 3, 2, 3, 2, 1, 6,
           2, 3, 3, 2, 2, 1, 3] # partnet
index_start = [0, 4, 6, 8, 12, 16, 19, 22, 24, 28, 30, 36, 38, 41, 44, 47]

def visualize_pts(points, colors):
    '''
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts.cpu().numpy())
    pcd.colors = o3d.utility.Vector3dVector(colors.cpu().numpy())
    o3d.visualization.draw_plotly([pcd],
                                  front=[0, 0, 1],
                                  lookat=[0, 0, 1],
                                  up=[0, 1, 0])
    '''
    points = points.numpy()
    fig = go.Figure(data=[go.Scatter3d(
        x=points[:, 0],
        y=points[:, 1],
        z=points[:, 2],
        mode='markers',
        marker=dict(
            size=2,
            color=(colors.numpy()*255).astype(int),  # Use RGB colors
            opacity=0.8
        ))])
    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    z_min, z_max = points[:, 2].min(), points[:, 2].max()
    fig.update_layout(
        scene=dict(
            xaxis=dict(title='x', range=[x_min, x_max]),
            yaxis=dict(title='y', range=[y_min, y_max]),
            zaxis=dict(title='z', range=[z_min, z_max]),
            aspectmode='manual',
            aspectratio=dict(
                x=(x_max - x_min),
                y=(y_max - y_min),
                z=(z_max - z_min)
            )
        ),
        scene_camera=dict(
            up=dict(x=0, y=1, z=0)  # Adjust these values for your point cloud
        )
    )
    fig.show()
    
def visualize_pt_labels(pts, labels): # pts is n*3, colors is n, 0 - n-1 where 0 is unlabeled
    part_num = labels.max()
    cmap_matrix = torch.tensor([[1,1,1], [1,1,0], [0,1,0], [0,0,1], [1,0,0], [1,0,1],
                [0,1,1], [0.5,0.5,0.5], [0.5,0.5,0], [0.5,0,0.5],[0,0.5,0.5],
                [0.1,0.2,0.3],[0.2,0.5,0.3], [0.6,0.3,0.2], [0.5,0.3,0.5],
                [0.6,0.7,0.2],[0.5,0.8,0.3]])[:part_num+1,:]
    colors = ["white", "yellow", "green", "blue", "red", "magenta", "cyan","grey", "olive",
                "purple", "teal", "navy", "darkgreen", "brown", "pinkpurple", "yellowgreen", "limegreen"]
    caption_list=[f"{i}:{colors[i]}" for i in range(part_num+1)]
    onehot = F.one_hot(labels.long(), num_classes=part_num+1) * 1.0 # n_pts, part_num+1, each row 00.010.0, first place is unlabeled (0 originally)
    pts_rgb = torch.matmul(onehot, cmap_matrix) # n_pts,3
    visualize_pts(pts, pts_rgb)
    print(caption_list)


def get_shapenetpart_tuned_prompt(clip_model, class_choice, searched_prompt=None):
    if not searched_prompt:
        sents = []
        sents = best_prompt[class_choice]
    else:
        sents = searched_prompt
    prompts = torch.cat([clip.tokenize(p) for p in sents]).cuda()
    text_feat = clip_model.encode_text(prompts)
    return text_feat, sents

def get_shapenetpart_generic_prompt(clip_model, class_choice, decorated = True):
    parts = cat2part[class_choice]
    if decorated:
        sents = [f"{part} of a {class_choice}" for part in parts]
    else:
        sents = parts
    prompts = torch.cat([clip.tokenize(p) for p in sents]).cuda()
    text_feat = clip_model.encode_text(prompts)
    return text_feat, sents


def get_partnete_generic_prompt(clip_model, class_choice, decorated = True):
    with open(f"/data/ziqi/partnet-mobility/PartNetE_meta.json") as f:
        all_mapping = json.load(f)
        parts = all_mapping[class_choice]
    if decorated:
        sents = [f"{part} of a {class_choice}" for part in parts]
    else:
        sents = parts
    sents.append("other")
    prompts = torch.cat([clip.tokenize(p) for p in sents]).cuda()
    text_feat = clip_model.encode_text(prompts)
    return text_feat, sents


def read_prompts():
    f = open('prompts/shapenetpart_700.json')
    data = json.load(f)
    return data

@torch.no_grad()
def search_prompt(class_choice, model_name, prompt_mode="tuned", searched_prompt=None, only_evaluate=True):    
    output_path = 'output/{}/{}'.format(model_name.replace('/', '_'), class_choice)
    
    # read saved feature maps, labels, point locations
    #print("\nReading saved feature maps of class {} ...".format(class_choice))
    test_pc = torch.load(osp.join(output_path, "test_pc.pt")).cuda()
    test_feat = torch.load(osp.join(output_path, "test_features.pt")).cuda()
    test_label = torch.load(osp.join(output_path, "test_labels.pt")) - index_start[cat2id[class_choice]]
    test_ifseen = torch.load(osp.join(output_path, "test_ifseen.pt"))
    test_pointloc = torch.load(osp.join(output_path, "test_pointloc.pt"))
    test_feat = test_feat.reshape(-1, 10, 196, 512)

    # encoding textual features
    clip_model, _ = clip.load(model_name)
    clip_model.eval()
    
    if prompt_mode == "tuned":
        text_feat, prompts = get_shapenetpart_tuned_prompt(clip_model, class_choice, searched_prompt)
    elif prompt_mode == "decorated":
        text_feat, prompts = get_shapenetpart_generic_prompt(clip_model, class_choice, decorated = True)
    elif prompt_mode == "part":
        text_feat, prompts = get_shapenetpart_generic_prompt(clip_model, class_choice, decorated = False)
    else:
        raise Exception("unknown prompt mode!")
    text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
    
    vweights = torch.Tensor(best_vweight[class_choice]).cuda()
    part_num = text_feat.shape[0]
    acc, iou = run_epoch(vweights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name, visualize=False, pc=test_pc)
    
    if only_evaluate:
        print('\nFor class {}, part segmentation Acc: {}, IoU: {}.\n'.format(class_choice, acc, iou))
        return iou
    
    print("\n***** Searching for prompts *****\n")
    print('\nBefore prompt search, Acc: {}, IoU: {}.\n'.format(acc, iou))    
    gpt_sents = read_prompts()
    best_acc = acc
    best_iou = iou
    for kk in range(0, 2):
        for ii in range(len(cat2part[class_choice])):
            for ss in range(len(gpt_sents[class_choice][cat2part[class_choice][ii]])):
                
                prompts_temp = prompts.copy()
                prompts_temp[ii] = gpt_sents[class_choice][cat2part[class_choice][ii]][ss]
                prompt_token = torch.cat([clip.tokenize(p) for p in prompts_temp]).cuda()
                text_feat = clip_model.encode_text(prompt_token)
                text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
                
                acc, iou = run_epoch(vweights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name)

                if iou > best_iou:
                    print('Acc: {:.2f}, IoU: {:.2f},  obj: {}, part: {}'.format(acc, iou, class_choice, cat2part[class_choice][ii]))
                    best_acc = acc
                    best_iou = iou
                    prompts = prompts_temp
    print(prompts)
    return prompts


@torch.no_grad()
def search_prompt_partm(class_choice, model_name, test_feat, test_label, test_ifseen, test_pointloc, decorated=True, searched_prompt=None, only_evaluate=True):    
    # output_path = 'output/{}/{}'.format(model_name.replace('/', '_'), class_choice)
    
    # read saved feature maps, labels, point locations
    #print("\nReading saved feature maps of class {} ...".format(class_choice))
    #test_feat = torch.load(osp.join(output_path, "test_features.pt")).cuda()
    #test_label = torch.load(osp.join(output_path, "test_labels.pt"))
    #test_ifseen = torch.load(osp.join(output_path, "test_ifseen.pt"))
    #test_pointloc = torch.load(osp.join(output_path, "test_pointloc.pt"))
    test_feat = test_feat.reshape(-1, 10, 196, 512)

    # encoding textual features
    clip_model, _ = clip.load(model_name)
    clip_model.eval()
    text_feat, prompts = get_partnete_generic_prompt(clip_model, class_choice, decorated = decorated)
    text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
    
    vweights = torch.ones(10).cuda()
    part_num = text_feat.shape[0]
    acc, iou = run_epoch_partnetm(vweights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name)
    
    if only_evaluate:
        return acc, iou
    
    print("\n***** Searching for prompts *****\n")
    print('\nBefore prompt search, Acc: {}, IoU: {}.\n'.format(acc, iou))    
    gpt_sents = read_prompts()
    best_acc = acc
    best_iou = iou
    for kk in range(0, 2):
        for ii in range(len(cat2part[class_choice])):
            for ss in range(len(gpt_sents[class_choice][cat2part[class_choice][ii]])):
                
                prompts_temp = prompts.copy()
                prompts_temp[ii] = gpt_sents[class_choice][cat2part[class_choice][ii]][ss]
                prompt_token = torch.cat([clip.tokenize(p) for p in prompts_temp]).cuda()
                text_feat = clip_model.encode_text(prompt_token)
                text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
                
                acc, iou = run_epoch(vweights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name)

                if iou > best_iou:
                    print('Acc: {:.2f}, IoU: {:.2f},  obj: {}, part: {}'.format(acc, iou, class_choice, cat2part[class_choice][ii]))
                    best_acc = acc
                    best_iou = iou
                    prompts = prompts_temp
    print(prompts)
    return prompts
                    
                    
@torch.no_grad()
def search_vweight(class_choice, model_name, searched_prompt=None):
    print("\n***** Searching for view weights *****\n")
    
    output_path = 'output/{}/{}'.format(model_name.replace('/', '_'), class_choice)
    
    test_feat = torch.load(osp.join(output_path, "test_features.pt")).cuda()
    test_label = torch.load(osp.join(output_path, "test_labels.pt")) - index_start[cat2id[class_choice]]
    test_ifseen = torch.load(osp.join(output_path, "test_ifseen.pt"))
    test_pointloc = torch.load(osp.join(output_path, "test_pointloc.pt"))
    test_feat = test_feat.reshape(-1, 10, 196, 512)

    clip_model, _ = clip.load(model_name)
    clip_model.eval()
    text_feat, prompts = textual_encoder(clip_model, class_choice, searched_prompt)
    text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
    
    vweights = torch.Tensor(best_vweight[class_choice]).cuda()
    part_num = text_feat.shape[0]
    #acc, iou = run_epoch(vweights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name)
    acc, iou = run_epoch_partnetm(vweights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name)
    print('\nBefore view weight search, Acc: {}, IoU: {}\n'.format(acc, iou))
    
    best_acc = acc
    best_iou = iou
    search_list = [0.25, 0.5, 0.75, 1.0]
    for a in search_list:
        for b in search_list:
            for c in search_list:
                for d in search_list:
                    for e in search_list:
                        for f in search_list:                                
                            view_weights = torch.tensor([0.75, 0.75, 0.75, 0.75, a, b, c, d, e, f]).cuda()
                            acc, iou = run_epoch(view_weights, test_feat, test_label, test_ifseen, test_pointloc, text_feat, part_num, class_choice, model_name)

                            if iou > best_iou:
                                vweights = [0.75, 0.75, 0.75, 0.75, a, b, c, d, e, f]
                                print('Acc: {:.2f}, IoU: {:.2f}, obj: {}, view weights: {:.2f}, {:.2f}, {:.2f}, {:.2f}, {:.2f}, {:.2f}, {:.2f}, {:.2f}, {:.2f}'.format(acc, iou, class_choice, 0.75, 0.75, 0.75, 0.75, a, b, c, d, e, f))
                                best_acc = acc
                                best_iou = iou
    
    print('\nAfter search, zero-shot segmentation IoU: {}'.format(best_iou))
    return vweights

                    
def run_epoch(vweights, val_feat, val_label, val_ifseen, val_pointloc, text_feat, part_num, class_choice, model_name, visualize=False, pc=None):
    
    val_size = val_feat.shape[0]
    bs = 30
    iter = val_size // bs
    pred_seg, label_seg, class_label = [], [], []
    for i in range(iter + 1):
        end = bs*i+bs if bs*i+bs < val_size else val_size
        feat, label = val_feat[bs*i:end], val_label[bs*i:end]
        is_seen, point_loc = val_ifseen[bs*i:end], val_pointloc[bs*i:end]
        
        b, nv, hw, c = feat.size(0), feat.size(1), feat.size(2), feat.size(3)
        feat = feat.reshape(b*nv, hw, c)
        point_loc = point_loc.reshape(b*nv, -1, 2)
        is_seen = is_seen.reshape(b*nv, -1, 1)
        
        # calculating logits of each pixel on the feature map
        logits = 100. * feat.half() @ text_feat.half().t()
        output = logits.float().permute(0,2,1).reshape(-1, part_num, int(hw**0.5), int(hw**0.5))
        
        # upsample to the original image size
        upsample = torch.nn.Upsample(size=224, mode='bilinear')  # nearest, bilinear
        avgpool = torch.nn.AvgPool2d(6,1,0)
        padding = torch.nn.ReplicationPad2d([2,3,2,3])
        
        output = avgpool(padding(output))
        output = upsample(output)
        
        # back-projecting to each points
        nbatch = torch.repeat_interleave(torch.arange(0, nv*b)[:,None], 2048).view(-1, ).cuda().long()
        yy = point_loc[:, :, 0].view(-1).long()
        xx = point_loc[:, :, 1].view(-1).long()

        point_logits = output[nbatch, :, yy, xx]
        point_logits = point_logits.view(b, nv, 2048, part_num)
        
        vweights = vweights.view(1, -1, 1, 1)
        is_seen = is_seen.reshape(b, nv, 2048, 1)

        # points logits is the weighted sum of pixel logits
        point_logits = torch.sum(point_logits * vweights * is_seen, dim=1)
        point_seg = torch.topk(point_logits, k=1, dim=-1)[1].squeeze()
        label = label.reshape(b, 2048)
        class_id = torch.Tensor([cat2id[class_choice]] * point_seg.shape[0])
        
        pred_seg.append(point_seg.reshape(-1, 2048))
        label_seg.append(label.reshape(-1, 2048))
        class_label.append(class_id.reshape(-1))
        
    pred_seg = torch.cat(pred_seg, dim=0)
    label_seg = torch.cat(label_seg, dim=0)
    class_label = torch.cat(class_label, dim=0)
    
    output_path = 'output/{}/{}'.format(model_name.replace('/', '_'), class_choice)
    torch.save(pred_seg,  osp.join(output_path, "test_segpred.pt"))


    if visualize:
        for i in [2]:
        #i = 0 # just visualize the first instance
            shape_ious, category = calculate_shape_IoU(pred_seg[i,:].unsqueeze(0).cpu().numpy(), label_seg[i,:].unsqueeze(0).cpu().numpy(), class_label, class_choice, eva=True)
            print(shape_ious)

            visualize_pt_labels(pc[i,:,:].cpu(), label_seg[i,:].cpu()+1)
            visualize_pt_labels(pc[i,:,:].cpu(), pred_seg[i,:].cpu()+1) # +1 so we don't have white

    
    # calculating segmentation acc
    ratio = (pred_seg == label_seg)
    acc = torch.sum(ratio.float(), dim=-1) / 2048
    acc = torch.mean(acc) * 100.
    
    # calculating iou
    pred_seg = pred_seg.cpu().numpy() 
    label_seg = label_seg.cpu().numpy()
    class_label = class_label.cpu().numpy()
    shape_ious, category = calculate_shape_IoU(pred_seg, label_seg, class_label, class_choice, eva=True)
    shape_ious = np.mean(np.array(shape_ious))
    
    return acc, shape_ious * 100.


def run_epoch_partnetm(vweights, val_feat, val_label, val_ifseen, val_pointloc, text_feat, part_num, class_choice, model_name):
    PC_NUM = val_label.shape[-1]
    val_size = val_feat.shape[0]
    bs = 30
    iter = val_size // bs
    pred_seg, label_seg, class_label = [], [], []
    for i in range(iter + 1):
        end = bs*i+bs if bs*i+bs < val_size else val_size
        feat, label = val_feat[bs*i:end], val_label[bs*i:end]
        is_seen, point_loc = val_ifseen[bs*i:end], val_pointloc[bs*i:end]
        
        b, nv, hw, c = feat.size(0), feat.size(1), feat.size(2), feat.size(3)
        feat = feat.reshape(b*nv, hw, c)
        point_loc = point_loc.reshape(b*nv, -1, 2)
        is_seen = is_seen.reshape(b*nv, -1, 1)
        
        # calculating logits of each pixel on the feature map
        logits = 100. * feat.half() @ text_feat.half().t()
        output = logits.float().permute(0,2,1).reshape(-1, part_num, int(hw**0.5), int(hw**0.5))
        
        # upsample to the original image size
        upsample = torch.nn.Upsample(size=224, mode='bilinear')  # nearest, bilinear
        avgpool = torch.nn.AvgPool2d(6,1,0)
        padding = torch.nn.ReplicationPad2d([2,3,2,3])
        
        output = avgpool(padding(output))
        output = upsample(output)
        
        # back-projecting to each points
        nbatch = torch.repeat_interleave(torch.arange(0, nv*b)[:,None], PC_NUM).view(-1, ).cuda().long()
        yy = point_loc[:, :, 0].view(-1).long()
        xx = point_loc[:, :, 1].view(-1).long()

        point_logits = output[nbatch, :, yy, xx]
        point_logits = point_logits.view(b, nv, PC_NUM, part_num)
        
        vweights = vweights.view(1, -1, 1, 1)
        is_seen = is_seen.reshape(b, nv, PC_NUM, 1)

        # points logits is the weighted sum of pixel logits
        point_logits = torch.sum(point_logits * vweights * is_seen, dim=1)
        point_seg = torch.topk(point_logits, k=1, dim=-1)[1].squeeze()
        # last category is "other", set to -1
        point_seg[point_seg==point_logits.shape[2]-1] = -1
        
        label = label.reshape(b, PC_NUM)
        class_id = torch.Tensor([cat2id[class_choice]] * point_seg.shape[0])
        
        pred_seg.append(point_seg.reshape(-1, PC_NUM))
        label_seg.append(label.reshape(-1, PC_NUM))
        class_label.append(class_id.reshape(-1))
        
    pred_seg = torch.cat(pred_seg, dim=0)
    label_seg = torch.cat(label_seg, dim=0)
    class_label = torch.cat(class_label, dim=0)
    
    output_path = 'output/{}/{}'.format(model_name.replace('/', '_'), class_choice)
    torch.save(pred_seg,  osp.join(output_path, "test_segpred.pt"))
    
    # calculating segmentation acc
    ratio = (pred_seg == label_seg).float()
    acc = torch.sum(ratio, dim=-1) / PC_NUM # acc of labeled objs
    acc = torch.mean(acc) * 100.
    
    # calculating iou
    pred_seg = pred_seg.cpu().numpy() 
    label_seg = label_seg.cpu().numpy()
    class_label = class_label.cpu().numpy()
    shape_ious, category = calculate_shape_IoU(pred_seg, label_seg, class_label, class_choice, eva=True)
    shape_ious = np.mean(np.array(shape_ious))
    
    return acc, shape_ious * 100.


def eval_sample_objaverse(feat, label, is_seen, point_loc, text_feat, part_num):
    PC_NUM = label.shape[-1]
    feat = feat.reshape(10, 196, 512)
    nv = feat.shape[0]
    hw = feat.shape[1]
    point_loc = point_loc.reshape(nv, -1, 2)
    is_seen = is_seen.reshape(nv, -1, 1)
        
    # calculating logits of each pixel on the feature map
    logits = 100. * feat.half() @ text_feat.half().t()
    output = logits.float().permute(0,2,1).reshape(-1, part_num+1, int(hw**0.5), int(hw**0.5))
        
    # upsample to the original image size
    upsample = torch.nn.Upsample(size=224, mode='bilinear')  # nearest, bilinear
    avgpool = torch.nn.AvgPool2d(6,1,0)
    padding = torch.nn.ReplicationPad2d([2,3,2,3])
        
    output = avgpool(padding(output))
    output = upsample(output)
        
    # back-projecting to each points
    nbatch = torch.repeat_interleave(torch.arange(0, nv)[:,None], PC_NUM).view(-1, ).cuda().long()
    yy = point_loc[:, :, 0].view(-1).long()
    xx = point_loc[:, :, 1].view(-1).long()

    point_logits = output[nbatch, :, yy, xx]
    point_logits = point_logits.view(nv, PC_NUM, part_num+1)
    is_seen = is_seen.reshape(nv, PC_NUM, 1)

    # points logits is the weighted sum of pixel logits
    point_logits = torch.sum(point_logits * is_seen, dim=0)
    point_seg = torch.topk(point_logits, k=1, dim=-1)[1].squeeze()
    # last category is "other", set to -1
    point_seg[point_seg==point_logits.shape[1]-1] = -1
        
    label = label.reshape(PC_NUM)
    # calculating segmentation acc
    ratio = (point_seg == label).float()
    acc = torch.sum(ratio, dim=-1) / PC_NUM # acc of labeled objs
    acc = torch.mean(acc) * 100.
    point_seg = point_seg.cpu().numpy()
    label = label.cpu().numpy()
    
    # calculating iou
    part_ious = []
    eval_part_num = int(np.max([label.max(), point_seg.max()]))+1 # this is the corner case where number of prompts passed in could be more than gt, in which case we take max
    for part in range(eval_part_num):
        I = np.sum(np.logical_and(point_seg == part, label == part))
        U = np.sum(np.logical_or(point_seg == part, label == part))
        if U == 0:
            pass  # If the union of groundtruth and prediction points is empty, then count part IoU as 1
        else:
            iou = I / float(U)
            part_ious.append(iou)
    mean_iou = np.mean(part_ious)*100.
    return acc, mean_iou, point_seg