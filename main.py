import argparse
import torch
import os
import sys
import warnings
from random import sample
import pickle as pkl
import numpy as np
import time
import shutil
from tqdm import tqdm

import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import MultiStepLR

import matplotlib.pyplot as plt
import shutil
from matplotlib import colors
from sklearn.metrics import mean_absolute_error
from scipy.stats import pearsonr
import seaborn as sns

import matplotlib as mpl
import matplotlib.cm as cm
import matplotlib.colors as mcolors

from per_site_cgcnn.data import PerSiteData
from per_site_cgcnn.data import collate_pool, get_train_val_test_loader
from per_site_cgcnn.model import PerSiteCGCNet#, BindingEnergyCGCNet 

#sys.path.append("../utils")
#from utils import *
#from surface_analyzer import *

import sigopt

os.environ["CUDA_VISIBLE_DEVICES"] = str(2)
assert torch.cuda.is_available(), "cuda is not available"

WORKDIR = os.getcwd()
best_mae_error = 1e10

#t_seed = random.randint(0,1000)
#t_seed = 0

def set_seed(seed: int = 42) -> None:
    np.random.seed(seed)
    #random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    # When running on the CuDNN backend, two further options must be set
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    # Set a fixed value for the hash seed
    os.environ["PYTHONHASHSEED"] = str(seed)
    print(f"Random seed set as {seed}")

    
device = 'cuda'

class Args():

    def __init__(self, 
            data = "data/all_combined.pkl",
            site_prop = ['magmom','bader','bandcenter'], 
            data_cache = "dataset_cache",
            workers = 0,
            epochs = 157,
            start_epoch = 0,
            batch_size = 64,
            lr = 0.00363,
            lr_milestones = 100,
            momentum = 0.9,
            weight_decay = 0,
            print_freq = 10,
            resume = "",
            train_ratio = 0.6,
            val_ratio = 0.2,
            test_ratio = 0.2, 
            optim = "Adam",
            atom_fea_len = 178,
            h_fea_len = 223,
            n_conv = 3,
            n_h = 2,
            sched = "Multi-step scheduler",
            lr_update_rate = 30,
            seed = 83,
            ):

        self.data = data
        self.site_prop = site_prop
        self.data_cache = data_cache
        self.workers = workers
        self.epochs = epochs
        self.start_epoch = start_epoch
        self.batch_size = batch_size
        self.lr = lr
        self.lr_milestones = lr_milestones
        self.momentum = momentum
        self.weight_decay = weight_decay
        self.print_freq = print_freq
        self.resume = resume
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        self.optim = optim
        self.atom_fea_len = atom_fea_len
        self.h_fea_len = h_fea_len
        self.n_conv = n_conv
        self.n_h = n_h
        self.sched = sched
        self.lr_update_rate = lr_update_rate
        self.seed = seed

def flatten(t):
    return [item for sublist in t for item in sublist]

def plot_hexbin(targ, pred, key, title="", scale="linear", 
                inc_factor = 1.1, dec_factor = 0.9,
                bins=None, plot_helper_lines=False,
                cmap='viridis'):
    
    props = {
        'center_diff': 'B 3d $-$ O 2p difference',
        'op': 'O 2p $-$ $E_v$',
        'form_e': 'formation energy',
        'e_hull': 'energy above hull',
        'tot_e': 'energy per atom',
        'time': 'runtime',
        'magmom': 'magnetic moment',
        'magmom_abs': 'magnetic moment',
        'ads_e': 'adsorption energy',
        'acid_stab': 'electrochemical stability',
        'bandcenter': 'DOS band center',
        'phonon': 'atomic vibration frequency',
        'bader': 'Bader charge'
    }
    
    units = {
        'center_diff': 'eV',
        'op': 'eV',
        'form_e': 'eV',
        'e_hull': 'eV/atom',
        'tot_e': 'eV/atom',
        'time': 's',
        'magmom': '$\mu_B$',
        'magmom_abs': '|$\mu_B$|',
        'ads_e': 'eV',
        'acid_stab': 'eV/atom',
        'bandcenter': 'eV',
        'phonon': 'THz',
        'bader': '$q_e$'
    }
    
    fig, ax = plt.subplots(figsize=(6,6))
    
    mae = mean_absolute_error(targ, pred)
    r, _ = pearsonr(targ, pred)
    
    if scale == 'log':
        pred = np.abs(pred) + 1e-8
        targ = np.abs(targ) + 1e-8
        
    lim_min = min(np.min(pred), np.min(targ))
    if lim_min < 0:
        if lim_min > -0.1:
            lim_min = -0.1
        lim_min *= inc_factor
    else:
        if lim_min < 0.1:
            lim_min = -0.1
        lim_min *= dec_factor
    lim_max = max(np.max(pred), np.max(targ))
    if lim_max <= 0:
        if lim_max > -0.1:
            lim_max = 0.2
        lim_max *= dec_factor
    else:
        if lim_max < 0.1:
            lim_max = 0.25
        lim_max *= inc_factor
        
    ax.set_xlim(lim_min, lim_max)
    ax.set_ylim(lim_min, lim_max)
    ax.set_aspect('equal')

    #ax.plot((lim_min, lim_max),
    #        (lim_min, lim_max),
    #        color='#000000',
    #        zorder=-1,
    #        linewidth=0.5)
    ax.axline((0, 0), (1, 1),
           color='#000000',
           zorder=-1,
           linewidth=0.5)
       
    hb = ax.hexbin(
        targ, pred,
        cmap=cmap,
        gridsize=60,
        bins=bins,
        mincnt=1,
        edgecolors=None,
        linewidths=(0.1,),
        xscale=scale,
        yscale=scale,
        extent=(lim_min, lim_max, lim_min, lim_max))
    

    cb = fig.colorbar(hb, shrink=0.822)
    cb.set_label('Count')

    if plot_helper_lines:
        
        if scale == 'linear':
            x = np.linspace(lim_min, lim_max, 50)
            y_up = x + mae
            y_down = x - mae         
            
        elif scale == 'log':
            x = np.logspace(np.log10(lim_min), np.log10(lim_max), 50)
            
            # one order of magnitude
            y_up = np.maximum(x + 1e-2, x * 10)
            y_down = np.minimum(np.maximum(1e-8, x - 1e-2), x / 10)
            
            # one kcal/mol/Angs
            y_up = x + 1
            y_down = np.maximum(1e-8, x - 1)
            
        
        for y in [y_up, y_down]:
            ax.plot(x,
                    y,
                    color='#000000',
                    zorder=2,
                    linewidth=0.5,
                    linestyle='--')
            
    ax.set_title(title, fontsize=14)
    ax.set_ylabel('Predicted %s [%s]' % (props[key], units[key]), fontsize=12)
    ax.set_xlabel('Calculated %s [%s]' % (props[key], units[key]), fontsize=12)
    
    ax.annotate("Pearson's r: %.3f \nMAE: %.3f %s " % (r, mae, units[key]),
                (0.03, 0.88),
                xycoords='axes fraction',
                fontsize=12)
         
    return r, mae, ax, hb

def get_val_mae(test_targets, test_preds, test_ids):

    mae = 0

    for i in [0,1,2,3]:
    
        site_targs = []
        site_preds = []

        for index in tqdm(range(len(test_ids))):
    
            id_ = test_ids[index]
        
            surface = Surface.objects.filter(id=id_)
            
            if surface:
                surf = surface[0]
                surface_atoms = np.where(surf.surface_atoms)[0]
                targ = np.array(test_targets[index])[:,i]
                pred = np.array(test_preds[index])[:,i]
                site_targs.append(np.array(targ[surface_atoms]))
                site_preds.append(np.array(pred[surface_atoms]))

        site_targs = flatten(site_targs)
        site_preds = flatten(site_preds)
        indexes = np.where(~np.isnan(np.array(site_targs)))[0]


        mae += mean_absolute_error(np.array(site_targs)[indexes], np.array(site_preds)[indexes])
        _, _, ax1, _ = plot_hexbin(np.array(site_targs)[indexes], np.array(site_preds)[indexes], 'op', bins='log', cmap='gray_r')

        label = 'descriptor'+str(i)
        ax1.set_xlabel(label)
        ax1.set_ylabel(label)
   
        plt.savefig(label+'.png')

    return mae/4 

def train(train_loader, model, criterion, optimizer, epoch, normalizer, args):

    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    mae_errors = AverageMeter()

    # switch to train mode
    model.train()

    end = time.time()
    for i, (inputs, target, _) in enumerate(train_loader):
        # measure data loading time
        data_time.update(time.time() - end)

        input_var = (
            inputs[0].to(device),
            inputs[1].to(device),
            inputs[2].to(device),
            [crys_idx.to(device) for crys_idx in inputs[3]]
        )

        target_normed = normalizer.norm(target)
        target_var = target_normed.to(device)

        # Compute output
        output, atom_fea = model(*input_var)
        output = torch.cat(output)
        #atom_fea = torch.cat(atom_fea).data.cpu()
        target_var = torch.cat([target_var[idx_map] for idx_map in inputs[3]])

        # calculate loss with nans removed
        output_flatten = torch.flatten(output)
        target_flatten = torch.flatten(target_var)
        valid_idx = torch.bitwise_not(torch.isnan(target_flatten))

        loss = criterion(output_flatten[valid_idx], target_flatten[valid_idx])

        # measure accuracy and record loss
        mae_error = mae(output_flatten[valid_idx], target_flatten[valid_idx])
        losses.update(loss.data.cpu().item(), target.size(0))
        mae_errors.update(mae_error.cpu().item(), target.size(0))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                    'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                    'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                    'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                    'MAE {mae_errors.val:.3f}  ({mae_errors.avg:.3f})'.format(
                epoch, i, len(train_loader), batch_time=batch_time,
                data_time=data_time, loss=losses, mae_errors=mae_errors)
            )

    return losses.avg, mae_errors.avg

def validate(val_loader, model, criterion, normalizer, args, test=False):

    batch_time = AverageMeter()
    losses = AverageMeter()
    mae_errors = AverageMeter()
    
    if test:
        test_targets = []
        test_preds = []
        test_ids = []

    # switch to evaluate mode
    model.eval()

    end = time.time()
    for i, (inputs, target, batch_ids) in enumerate(val_loader):

        input_var = (
            inputs[0].to(device),
            inputs[1].to(device),
            inputs[2].to(device),
            [crys_idx.to(device) for crys_idx in inputs[3]]
        )

        target_normed = normalizer.norm(target)

        target_var = target_normed.to(device)

        # Compute output
        output, atom_fea = model(*input_var)
        output = torch.cat(output)
        
        # calculate loss with nans removed
        output_flatten = torch.flatten(output)
        target_flatten = torch.flatten(target_var)
        valid_idx = torch.bitwise_not(torch.isnan(target_flatten))

        loss = criterion(output_flatten[valid_idx], target_flatten[valid_idx])

        # measure accuracy and record loss
        mae_error = mae(output_flatten[valid_idx], target_flatten[valid_idx])
        losses.update(loss.data.cpu().item(), target.size(0))
        mae_errors.update(mae_error.cpu().item(), target.size(0))
        
        if test:
            test_pred = normalizer.denorm(output.data.cpu())
            test_target = target
            test_preds += [test_pred[i] for i in inputs[3]]
            test_targets += [test_target[i] for i in inputs[3]]
            test_ids += batch_ids

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            print('Test: [{0}/{1}]\t'
                    'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                    'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                    'MAE {mae_errors.val:.3f} ({mae_errors.avg:.3f})'.format(
                i, len(val_loader), batch_time=batch_time, loss=losses,
                mae_errors=mae_errors))

    if test:
        star_label = '**'
        print(' {star} MAE {mae_errors.avg:.3f}'.format(star=star_label,
                                                        mae_errors=mae_errors))
        return test_targets, test_preds, test_ids
    else:
        star_label = '*'
    
    print(' {star} MAE {mae_errors.avg:.3f}'.format(star=star_label,
                                                        mae_errors=mae_errors))
    return losses.avg, mae_errors.avg

class Normalizer(object):
    """Normalize a Tensor and restore it later. """

    def __init__(self, tensor):
        """tensor is taken as a sample to calculate the mean and std"""
    
        tensor_flatten = torch.flatten(tensor)
        valid_idx = torch.bitwise_not(torch.isnan(tensor_flatten))
        self.mean = torch.mean(tensor_flatten[valid_idx])
        self.std = torch.std(tensor_flatten[valid_idx])

    def norm(self, tensor):
        return (tensor - self.mean) / self.std

    def denorm(self, normed_tensor):
        return normed_tensor * self.std + self.mean

    def state_dict(self):
        return {'mean': self.mean,
                'std': self.std}

    def load_state_dict(self, state_dict):
        self.mean = state_dict['mean']
        self.std = state_dict['std']

def mae(prediction, target):
    """
    Computes the mean absolute error between prediction and target

    Parameters
    ----------

    prediction: torch.Tensor (N, 1)
    target: torch.Tensor (N, 1)
    """
    return torch.mean(torch.abs(target - prediction))

class AverageMeter(object):
    """Computes and stores the average and current value"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'model_best.pth.tar')


def adjust_learning_rate(optimizer, epoch, k):
    """Sets the learning rate to the initial LR decayed by 10 every k epochs"""
    assert type(k) is int
    lr = args.lr * (0.1 ** (epoch // k))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def main(args):
    
    global best_mae_error, WORKDIR

    set_seed(args.seed) # set torch, python, etc. seeds

    # load data
    data = pkl.load(open(args.data, 'rb'))
    samples = [[id_, struct] for id_, struct in data.items()]

    dataset = PerSiteData(samples, args.site_prop, WORKDIR, args.data_cache, random_seed=args.seed)
    collate_fn = collate_pool
    train_loader, val_loader, test_loader = get_train_val_test_loader(
        dataset=dataset,
        collate_fn=collate_fn,
        batch_size=args.batch_size,
        train_ratio=args.train_ratio,
        num_workers=args.workers,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        return_test=True)

    if len(dataset) < 500:
        warnings.warn('Dataset has less than 500 data points. '
                  'Lower accuracy is expected. ')
        sample_data_list = [dataset[i] for i in range(len(dataset))]
    else:
        sample_data_list = [dataset[i] for i in
                        sample(range(len(dataset)), 500)]
    _, sample_target, _ = collate_pool(sample_data_list)
    normalizer = Normalizer(sample_target)


    structures, _, _ = dataset[0]
    orig_atom_fea_len = structures[0].shape[-1]
    nbr_fea_len = structures[1].shape[-1]
    model = PerSiteCGCNet(orig_atom_fea_len, nbr_fea_len, len(args.site_prop),
                            atom_fea_len=args.atom_fea_len,
                            n_conv=args.n_conv,
                            h_fea_len=args.h_fea_len,
                            n_h=args.n_h)
    param_list = []
    param_list.append(model.fc_out.weight.detach().cpu().numpy())

    model.cuda()

    # define loss func and optimizer
    criterion = nn.MSELoss()

    if args.optim == 'SGD':
        optimizer = optim.SGD(model.parameters(), args.lr,
                          momentum=args.momentum,
                          weight_decay=args.weight_decay)
    elif args.optim == 'Adam':
        optimizer = optim.Adam(model.parameters(), args.lr,
                           weight_decay=args.weight_decay)
    else:
        raise NameError('Only SGD or Adam is allowed as --optim')

    # optionally resume from a checkpoint
    if args.resume:
        if os.path.isfile(args.resume):
            print("=> loading checkpoint '{}'".format(args.resume))
            checkpoint = torch.load(args.resume)
            args.start_epoch = checkpoint['epoch']
            best_mae_error = checkpoint['best_mae_error']
            model.load_state_dict(checkpoint['state_dict'])
            optimizer.load_state_dict(checkpoint['optimizer'])
            normalizer.load_state_dict(checkpoint['normalizer'])
            print("=> loaded checkpoint '{}' (epoch {})"
                  .format(args.resume, checkpoint['epoch']))
        else:
            print("=> no checkpoint found at '{}'".format(args.resume))

    # set scheduler
    if args.sched == "cos_anneal":
        print("Cosine anneal scheduler")
        scheduler = CosineAnnealingLR(optimizer, args.lr_update_rate)
    elif args.sched == "cos_anneal_warm_restart":
        print("Cosine anneal with warm restarts scheduler")
        scheduler = CosineAnnealingWarmRestarts(optimizer, arhs.lr_update_rate)
    elif args.sched == "reduce_on_plateau":
        print("Reduce on plateau scheduler")
        scheduler = ReduceLROnPlateau(optimizer, 'min')
    else:
        print("Multi-step scheduler")
        lr_milestones = np.arange(args.lr_update_rate,args.epochs+args.lr_update_rate,args.lr_update_rate)
        scheduler = MultiStepLR(optimizer, milestones=lr_milestones,
                        gamma=0.1)

    # train model
    train_losses = []
    train_mae_errors = []
    val_losses = []
    val_mae_errors = []

    for epoch in range(args.start_epoch, args.epochs):

        # train for one epoch
        train_loss, train_mae_error = train(train_loader, model, criterion, optimizer, epoch, normalizer, args)
        train_losses.append(train_loss)
        train_mae_errors.append(train_mae_error)

        # evaluate on validation set
        val_loss, val_mae_error = validate(val_loader, model, criterion, normalizer, args)
        val_losses.append(val_loss)
        val_mae_errors.append(val_mae_error)

        if val_mae_error != val_mae_error:
            print('Exit due to NaN')
            sys.exit(1)

        scheduler.step()

        # Remember the best mae_error and save checkpoint
        is_best = val_mae_error < best_mae_error
        best_mae_error = min(val_mae_error, best_mae_error)
        save_checkpoint({
            'epoch': epoch + 1,
            'state_dict': model.state_dict(),
            'best_mae_error': best_mae_error,
            'optimizer': optimizer.state_dict(),
            'normalizer': normalizer.state_dict(),
            'args': vars(args)
        }, is_best)

        # Evaluate when to end training on account of no MAE improvement
        count = 0
        if is_best:
            count = 0
        else:
            count += 1
        if count > args.lr_update_rate*1.5 and count > 15:
            break

    # load the best model
    best_checkpoint = torch.load('model_best.pth.tar')
    model.load_state_dict(best_checkpoint['state_dict'])
    

    # test model
    train_targets, train_preds, train_ids = validate(train_loader, model, criterion, normalizer, args, test=True)
    val_targets, val_preds, val_ids = validate(val_loader, model, criterion, normalizer, args, test=True)
    #return get_val_mae(val_targets, val_preds, val_ids)

    test_targets, test_preds, test_ids = validate(test_loader, model, criterion, normalizer, args, test=True)
    # Save Test Results
    pkl.dump(test_ids, open(f"test_ids.pkl", "wb"))
    pkl.dump(test_preds, open(f"test_preds.pkl", "wb"))
    pkl.dump(test_targets, open(f"test_targs.pkl", "wb"))
    
    pkl.dump(train_ids, open(f"train_ids.pkl", "wb"))
    pkl.dump(train_preds, open(f"train_preds.pkl", "wb"))
    pkl.dump(train_targets, open(f"train_targs.pkl", "wb"))
    
    pkl.dump(val_ids, open(f"val_ids.pkl", "wb"))
    pkl.dump(val_preds, open(f"val_preds.pkl", "wb"))
    pkl.dump(val_targets, open(f"val_targs.pkl", "wb"))

args = Args(data='data/all_combined_clean_surface_and_bulk_no_benchmark_newref.pkl')
#args = Args(data='data/bulk_dos_newref.pkl')
#args = Args(data='data/bulk_bader_smaller.pkl')
#args = Args(data='data/bulk_phonons.pkl')

mae = main(args)
