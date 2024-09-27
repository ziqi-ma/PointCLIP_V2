import os
import glob
import h5py
import random
import numpy as np
from torch.utils.data import Dataset
import torch
import meshio
import open3d as o3d
import json

id2cat = ['airplane', 'bag', 'cap', 'car', 'chair', 'earphone', 'guitar', 'knife', 'lamp', 'laptop', 
        'motorbike', 'mug', 'pistol', 'rocket', 'skateboard', 'table']
cat2part = {'airplane': ['body','wing','tail','engine or frame'], 'bag': ['handle','body'], 'cap': ['panels or crown','visor or peak'], 
            'car': ['roof','hood','wheel or tire','body'],
            'chair': ['back','seat pad','leg','armrest'], 'earphone': ['earcup','headband','data wire'], 
            'guitar': ['head or tuners','neck','body'], 
            'knife': ['blade', 'handle'], 'lamp': ['leg or wire','lampshade'], 
            'laptop': ['keyboard','screen or monitor'], 
            'motorbike': ['gas tank','seat','wheel','handles or handlebars','light','engine or frame'], 'mug': ['handle', 'cup'], 
            'pistol': ['barrel', 'handle', 'trigger and guard'], 
            'rocket': ['body','fin','nose cone'], 'skateboard': ['wheel','deck','belt for foot'], 'table': ['desktop','leg or support','drawer'],
            'Bottle': ['lid', 'other']}
id2part2cat = [['body', 'airplane'], ['wing', 'airplane'], ['tail', 'airplane'], ['engine or frame', 'airplane'], ['handle', 'bag'], ['body', 'bag'], 
            ['panels or crown', 'cap'], ['visor or peak', 'cap'],
            ['roof', 'car'], ['hood', 'car'], ['wheel or tire',  'car'], ['body', 'car'],
            ['backrest or back', 'chair'], ['seat', 'chair'], ['leg or support', 'chair'], ['armrest', 'chair'], 
            ['earcup', 'earphone'], ['headband', 'earphone'], ['data wire',  'earphone'], 
            ['head or tuners', 'guitar'], ['neck', 'guitar'], ['body', 'guitar'], ['blade', 'knife'], ['handle', 'knife'], 
            ['support or tube of wire', 'lamp'], ['lampshade', 'lamp'], ['canopy', 'lamp'], ['support or tube of wire', 'lamp'], 
            ['keyboard', 'laptop'], ['screen or monitor', 'laptop'], ['gas tank', 'motorbike'], ['seat', 'motorbike'], ['wheel', 'motorbike'], 
            ['handles or handlebars', 'motorbike'], ['light', 'motorbike'], ['engine or frame', 'motorbike'], ['handle', 'mug'], ['cup or body', 'mug'], 
            ['barrel', 'pistol'], ['handle', 'pistol'], ['trigger and guard', 'pistol'], ['body', 'rocket'], ['fin', 'rocket'], ['nose cone', 'rocket'], 
            ['wheel', 'skateboard'], ['deck',  'skateboard'], ['belt for foot', 'skateboard'], 
            ['desktop', 'table'], ['leg or support', 'table'], ['drawer''table']]


def download_shapenetpart(data_path):
    if not os.path.exists(data_path):
        os.mkdir(data_path)
    if not os.path.exists(os.path.join(data_path, 'shapenet_part_seg_hdf5_data')):
        os.mkdir(os.path.join(data_path, 'shapenet_part_seg_hdf5_data'))
        www = 'https://shapenet.cs.stanford.edu/media/shapenet_part_seg_hdf5_data.zip'
        zipfile = os.path.basename(www)
        os.system('wget %s --no-check-certificate; unzip %s' % (www, zipfile))
        os.system('mv %s %s' % (zipfile[:-4], os.path.join(data_path, 'shapenet_part_seg_hdf5_data')))
        os.system('rm %s' % (zipfile))
        

def rotate_pts(pts, angles, device=None): # list of points as a tensor, N*3

    roll = angles[0].reshape(1)
    yaw = angles[1].reshape(1)
    pitch = angles[2].reshape(1)

    tensor_0 = torch.zeros(1).to(device)
    tensor_1 = torch.ones(1).to(device)

    RX = torch.stack([
                    torch.stack([tensor_1, tensor_0, tensor_0]),
                    torch.stack([tensor_0, torch.cos(roll), -torch.sin(roll)]),
                    torch.stack([tensor_0, torch.sin(roll), torch.cos(roll)])]).reshape(3,3)

    RY = torch.stack([
                    torch.stack([torch.cos(yaw), tensor_0, torch.sin(yaw)]),
                    torch.stack([tensor_0, tensor_1, tensor_0]),
                    torch.stack([-torch.sin(yaw), tensor_0, torch.cos(yaw)])]).reshape(3,3)

    RZ = torch.stack([
                    torch.stack([torch.cos(pitch), -torch.sin(pitch), tensor_0]),
                    torch.stack([torch.sin(pitch), torch.cos(pitch), tensor_0]),
                    torch.stack([tensor_0, tensor_0, tensor_1])]).reshape(3,3)

    R = torch.mm(RZ, RY)
    R = torch.mm(R, RX)
    if device == "cuda":
        R = R.cuda()
    pts_new = torch.mm(pts, R.T)
    return pts_new

def load_data_partseg(data_path, partition):
    #download_shapenetpart(data_path)
    all_data = []
    all_label = []
    all_seg = []

    if partition == 'trainval':
        file = glob.glob(os.path.join(data_path, 'hdf5_data', '*train*.h5')) \
               + glob.glob(os.path.join(data_path, 'hdf5_data', '*val*.h5'))
    elif partition == 'train':
        file = glob.glob(os.path.join(data_path, 'hdf5_data', '*train*.h5'))
    elif partition == 'val':
        file = glob.glob(os.path.join(data_path, 'hdf5_data', '*val*.h5'))
    else:
        file = glob.glob(os.path.join(data_path, 'hdf5_data', '*test*.h5'))
    for h5_name in file:
        f = h5py.File(h5_name, 'r+')
        data = f['data'][:].astype('float32')
        label = f['label'][:].astype('int64')
        seg = f['pid'][:].astype('int64')
        f.close()
        all_data.append(data)
        all_label.append(label)
        all_seg.append(seg)
    all_data = np.concatenate(all_data, axis=0)
    all_label = np.concatenate(all_label, axis=0)
    all_seg = np.concatenate(all_seg, axis=0)
    #print(all_data.shape)
    # get random rotation
    # first time, generate random rotation
    #if not os.path.exists(f"{data_path}/random_rotation_test.pt"):
        #all_rotation = torch.rand(all_data.shape[0],3)*2*3.14
        #torch.save(all_rotation, f"{data_path}/random_rotation_test.pt")
    all_rotation = torch.load(f"{data_path}/random_rotation_test.pt")

    if partition == 'test':
        return all_data, all_label, all_seg, all_rotation
    else:
        kshot = 16
        category_num = {}
        for i in range(16):
            category_num[i] = []
        for j in range(all_label.shape[0]):
            category_num[int(all_label[j,0])].append(j)

        all_data1, all_label1, all_seg1 = [], [], []
        
        for i in range(16):
            list = range(0, len(category_num[i]))
            nums = random.sample(list, kshot)
            for n in nums:
                all_data1.append(all_data[category_num[i][n],:,:][None, :,:])
                all_label1.append(all_label[category_num[i][n]][:, None])
                all_seg1.append(all_seg[category_num[i][n]][None,:])
        
        all_data1 = np.concatenate(all_data1, axis=0)
        all_label1 = np.concatenate(all_label1, axis=0)
        all_seg1 = np.concatenate(all_seg1, axis=0)
        return all_data1, all_label1, all_seg1


class ShapeNetPart(Dataset): # this is their code, only changing filepath
    def __init__(self, data_path='/data/ziqi/shapenetpart', num_points=2048, partition='test', class_choice=None):
        self.data, self.label, self.seg, self.rotation = load_data_partseg(data_path, partition)
        self.cat2id = {'airplane': 0, 'bag': 1, 'cap': 2, 'car': 3, 'chair': 4, 
                       'earphone': 5, 'guitar': 6, 'knife': 7, 'lamp': 8, 'laptop': 9, 
                       'motorbike': 10, 'mug': 11, 'pistol': 12, 'rocket': 13, 'skateboard': 14, 'table': 15}
        self.seg_num = [4, 2, 2, 4, 4, 3, 3, 2, 4, 2, 6, 2, 3, 3, 3, 3]
        self.index_start = [0, 4, 6, 8, 12, 16, 19, 22, 24, 28, 30, 36, 38, 41, 44, 47]
        self.num_points = num_points
        self.partition = partition        
        self.class_choice = class_choice

        if self.class_choice != None:
            id_choice = self.cat2id[self.class_choice]
            indices = (self.label == id_choice).squeeze()
            self.data = self.data[indices]
            self.label = self.label[indices]
            self.seg = self.seg[indices]
            self.seg_num_all = self.seg_num[id_choice]
            self.seg_start_index = self.index_start[id_choice]
            self.rotation = self.rotation[indices]
        else:
            self.seg_num_all = 50
            self.seg_start_index = 0

    def __getitem__(self, item):
        pointcloud = self.data[item][:self.num_points]
        # random rotation
        rot = self.rotation[item,:]
        rotated_pts = rotate_pts(torch.tensor(pointcloud), rot)
        label = self.label[item]
        seg = self.seg[item][:self.num_points]
        return rotated_pts, seg
    
    def __len__(self):
        return self.data.shape[0]
    

class ShapeNetPartSmall(Dataset): # this is subsampling 10 per class
    def __init__(self, data_path='/data/ziqi/shapenetpart', apply_rotation=False, num_points=2048, partition='test', class_choice=None):
        self.data, self.label, self.seg, self.rotation = load_data_partseg(data_path, partition)
        self.cat2id = {'airplane': 0, 'bag': 1, 'cap': 2, 'car': 3, 'chair': 4, 
                       'earphone': 5, 'guitar': 6, 'knife': 7, 'lamp': 8, 'laptop': 9, 
                       'motorbike': 10, 'mug': 11, 'pistol': 12, 'rocket': 13, 'skateboard': 14, 'table': 15}
        self.seg_num = [4, 2, 2, 4, 4, 3, 3, 2, 4, 2, 6, 2, 3, 3, 3, 3]
        self.index_start = [0, 4, 6, 8, 12, 16, 19, 22, 24, 28, 30, 36, 38, 41, 44, 47]
        self.num_points = num_points
        self.partition = partition        
        self.class_choice = class_choice
        self.apply_rotation = apply_rotation

        if self.class_choice != None:
            id_choice = self.cat2id[self.class_choice]
            indices = (self.label == id_choice).squeeze()
            self.data = self.data[indices]
            self.label = self.label[indices]
            self.seg = self.seg[indices]
            self.seg_num_all = self.seg_num[id_choice]
            self.seg_start_index = self.index_start[id_choice]
            self.rotation = self.rotation[indices]
            # get subset
            subset_idxs = np.loadtxt(f"/data/ziqi/shapenetpart/{class_choice}_subsample.txt").astype(int)
            print(subset_idxs)
            self.data = self.data[subset_idxs]
            self.label = self.label[subset_idxs]
            self.seg = self.seg[subset_idxs]
            self.rotation = self.rotation[subset_idxs]
        else:
            raise Exception("must have class")

    def __getitem__(self, item):
        pointcloud = self.data[item][:self.num_points]
        seg = self.seg[item][:self.num_points]
        
        if self.apply_rotation:
            # random rotation
            rot = self.rotation[item,:]
            rotated_pts = rotate_pts(torch.tensor(pointcloud), rot)
            label = self.label[item]
            return rotated_pts, seg
        else:
            return torch.tensor(pointcloud), seg
    
    def __len__(self):
        return self.data.shape[0]
    

    

class PartNetMobility(Dataset):
    def __init__(self, class_choice, data_path='/data/ziqi/partnet-mobility/test', partition='test'):
        self.partition = partition        
        self.class_choice = class_choice
        self.data_paths = [f"{data_path}/{class_choice}/{id}" for id in os.listdir(f"{data_path}/{class_choice}") if "delete" not in id and "txt" not in id]
        #print(len(self.data_paths))

    def __getitem__(self, item):
        obj_dir = self.data_paths[item]
        mesh = meshio.read(f"{obj_dir}/pc.ply")
        xyz = np.asarray(mesh.points) 
        xyz = xyz - xyz.mean(axis=0)
        xyz = xyz / np.linalg.norm(xyz, ord=2, axis=1).max().item()
        labels_in = torch.tensor(np.load(f"{obj_dir}/label.npy",allow_pickle=True).item()['semantic_seg'])

        # random rotation
        rot = torch.load(f"{obj_dir}/rand_rotation.pt")
        rotated_pts = rotate_pts(torch.tensor(xyz), rot)

        return rotated_pts, labels_in # torch.tensor(xyz), labels_in
    
    def __len__(self):
        return len(self.data_paths)
    

class PartNetMobilitySmall(Dataset):
    def __init__(self, class_choice, data_path='/data/ziqi/partnet-mobility/test', apply_rotation=False, partition='test'):
        self.partition = partition        
        self.class_choice = class_choice
        self.apply_rotation = apply_rotation
        with open(f"{data_path}/{class_choice}/subsampled_ids.txt", 'r') as f:
            self.data_paths = f.read().splitlines()

    def __getitem__(self, item):
        obj_dir = self.data_paths[item]
        mesh = meshio.read(f"{obj_dir}/pc.ply")
        xyz = np.asarray(mesh.points) 
        xyz = xyz - xyz.mean(axis=0)
        xyz = xyz / np.linalg.norm(xyz, ord=2, axis=1).max().item()
        labels_in = torch.tensor(np.load(f"{obj_dir}/label.npy",allow_pickle=True).item()['semantic_seg'])

        # random rotation
        if self.apply_rotation:
            rot = torch.load(f"{obj_dir}/rand_rotation.pt")
            rotated_pts = rotate_pts(torch.tensor(xyz), rot)
            return rotated_pts, labels_in
        else:
            return torch.tensor(xyz), labels_in #rotated_pts, labels_in # 
    
    def __len__(self):
        return len(self.data_paths)
    

class Objaverse(Dataset):
    def __init__(self, data_path='/data/ziqi/objaverse/holdout', partition='seenclass'):
        self.partition = partition
        self.data_paths = [f"{data_path}/{partition}/{cat_id}" for cat_id in os.listdir(f"{data_path}/{partition}") if "delete" not in cat_id]

    def __getitem__(self, item):
        obj_dir = self.data_paths[item]
        cat = obj_dir.split("/")[-1].split("_")[0]
        pcd = o3d.io.read_point_cloud(f"{obj_dir}/points5000.pcd")
        xyz = np.asarray(pcd.points)
        xyz = xyz - xyz.mean(axis=0)
        xyz = xyz / np.linalg.norm(xyz, ord=2, axis=1).max().item()
        labels_in = np.load(f"{obj_dir}/labels.npy") - 1 # originally 0 is unlabeled so on so forth
        # now becomes -1
        with open(f"{obj_dir}/label_map.json") as f:
            mapping = json.load(f)
        label_texts = []
        for i in range(len(mapping)):
            label_texts.append(mapping[str(i+1)]) # label starts from 1
        
        return torch.tensor(xyz).float(), labels_in, label_texts, cat
    
    def __len__(self):
        return len(self.data_paths)

