import torch
import random
import numpy as np
import pandas as pd
import torch.nn as nn
import argparse, logging
import torch.multiprocessing
import copy, time, pickle, shutil, sys, os, pdb

from copy import deepcopy
from pathlib import Path

sys.path.append(os.path.join(str(Path(os.path.realpath(__file__)).parents[2]), 'model'))
sys.path.append(os.path.join(str(Path(os.path.realpath(__file__)).parents[2]), 'dataloader'))
sys.path.append(os.path.join(str(Path(os.path.realpath(__file__)).parents[2]), 'trainers'))
sys.path.append(os.path.join(str(Path(os.path.realpath(__file__)).parents[2]), 'constants'))

import constants
from dataload_manager import dataload_manager
from mm_models import audio_video_classifier
from client_trainer import Client
from server_trainer import Server

# define logging console
import logging
logging.basicConfig(format='%(asctime)s %(levelname)-3s ==> %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')


def set_seed(seed):
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)


def parse_args():
    parser = argparse.ArgumentParser(description='FedMultimoda experiments')
    parser.add_argument(
        '--data_dir', 
        default='/media/data/projects/speech-privacy/fed-multimodal/',
        type=str, 
        help='output feature directory')
    
    parser.add_argument(
        '--audio_feat', 
        default='mfcc',
        type=str,
        help="audio feature name",
    )
    
    parser.add_argument(
        '--video_feat', 
        default='mobilenet_v2',
        type=str,
        help="video feature name",
    )
    
    parser.add_argument(
        '--learning_rate', 
        default=0.05,
        type=str,
        help="learning rate",
    )
    
    parser.add_argument(
        '--sample_rate', 
        default=0.2,
        type=str,
        help="client sample rate",
    )
    
    parser.add_argument(
        '--num_epochs', 
        default=300,
        type=str,
        help="total training rounds",
    )
    
    parser.add_argument(
        '--local_epochs', 
        default=1,
        type=int,
        help="local epochs",
    )
    
    parser.add_argument(
        '--optimizer', 
        default='sgd',
        type=str,
        help="optimizer",
    )
    
    parser.add_argument(
        '--fed_alg', 
        default='fed_avg',
        type=str,
        help="federated learning aggregation algorithm",
    )
    
    parser.add_argument(
        '--batch_size',
        default=16,
        type=int,
        help="training batch size",
    )
    
    parser.add_argument(
        "--alpha",
        type=float,
        default=1.0,
        help="alpha in direchlet distribution",
    )
    
    parser.add_argument(
        "--missing_modality",
        type=bool, 
        default=False,
        help="missing modality simulation",
    )
    
    parser.add_argument(
        "--en_missing_modality",
        dest='missing_modality',
        action='store_true',
        help="enable missing modality simulation",
    )
    
    parser.add_argument(
        "--missing_modailty_rate",
        type=float, 
        default=0.5,
        help='missing rate for modality; 0.9 means 90%% missing'
    )
    
    parser.add_argument(
        "--missing_label",
        type=bool, 
        default=False,
        help="missing label simulation",
    )
    
    parser.add_argument(
        "--en_missing_label",
        dest='missing_label',
        action='store_true',
        help="enable missing label simulation",
    )
    
    parser.add_argument(
        "--missing_label_rate",
        type=float, 
        default=0.5,
        help='missing rate for modality; 0.9 means 90%% missing'
    )
    
    parser.add_argument(
        '--label_nosiy', 
        type=bool, 
        default=False,
        help='clean label or nosiy label')
    
    parser.add_argument(
        "--en_label_nosiy",
        dest='label_nosiy',
        action='store_true',
        help="enable label noise simulation",
    )

    parser.add_argument(
        '--label_nosiy_level', 
        type=float, 
        default=0.1,
        help='nosiy level for labels; 0.9 means 90% wrong')
    
    parser.add_argument("--dataset", default="ucf101")
    args = parser.parse_args()
    return args

if __name__ == '__main__':

    # argument parser
    args = parse_args()

    # data manager
    dm = dataload_manager(args)
    dm.get_simulation_setting(alpha=args.alpha)
    
    # find device
    device = torch.device("cuda:1") if torch.cuda.is_available() else "cpu"
    if torch.cuda.is_available(): print('GPU available, use GPU')

    save_result_df = pd.DataFrame()

    # We perform 3 fold experiments
    for fold_idx in range(3):
        # load simulation feature
        dm.load_sim_dict(fold_idx=fold_idx+1)
        # load all data
        dm.load_full_audio_feat(fold_idx=fold_idx+1)
        dm.load_full_video_feat(fold_idx=fold_idx+1)
        # set dataloaders
        dataloader_dict = dict()
        for client_id in dm.train_audio:
            dataloader_dict[client_id] = dm.set_dataloader(client_id, shuffle=True)
        dataloader_dict['dev'] = dm.set_dataloader('dev', shuffle=False)
        dataloader_dict['test'] = dm.set_dataloader('test', shuffle=False)
        
        # number of clients
        num_of_clients, client_ids = len(dm.train_audio), list(dm.train_audio.keys())
        # set seeds
        set_seed(8)
        # loss function
        criterion = nn.NLLLoss().to(device)
        # Define the model
        global_model = audio_video_classifier(num_classes=constants.num_class_dict[args.dataset],
                                              audio_input_dim=constants.feature_len_dict["mfcc"], 
                                              video_input_dim=constants.feature_len_dict["mobilenet_v2"])
        global_model = global_model.to(device)

        # initialize server
        server = Server(args, global_model, device=device, criterion=criterion)
        server.initialize_log(fold_idx+1)
        server.sample_clients(num_of_clients, sample_rate=args.sample_rate)
        
        # set seeds again
        set_seed(8)

        # Training steps
        for epoch in range(int(args.num_epochs)):
            # define list varibles that saves the weights, loss, num_sample, etc.
            server.initialize_epoch_updates(epoch)
            # 1. Local training, return weights in fed_avg, return gradients in fed_sgd
            for idx in server.clients_list[epoch]:
                # Local training
                client_id = client_ids[idx]
                dataloader = dataloader_dict[client_id]
                # initialize client object
                client = Client(args, device, criterion, dataloader, copy.deepcopy(server.global_model))
                client.update_weights()
                # server append updates
                server.save_train_updates(copy.deepcopy(client.get_parameters()), client.result['sample'], client.result)
                del client
            
            # 2. aggregate, load new global weights
            server.average_weights()

            logging.info('---------------------------------------------------------')
            with torch.no_grad():
                # 3. Perform the validation on dev set
                server.inference(dataloader_dict['dev'])
                server.result_dict[epoch]['dev'] = server.result
                server.log_result(data_split='dev')

                # 4. Perform the test on holdout set
                server.inference(dataloader_dict['test'])
                server.result_dict[epoch]['test'] = server.result
                server.log_result(data_split='test')
            
            logging.info('---------------------------------------------------------')
            server.log_epoch_result(metric='acc')
            logging.info('---------------------------------------------------------')

        # Performance save code
        row_df = server.summarize_results()
        save_result_df = pd.concat([save_result_df, row_df])
        
    # Calculate the average of the 5-fold experiments
    row_df = pd.DataFrame(index=['average'])
    for metric in ['acc', 'top5_acc', 'uar']:
        row_df[metric] = np.mean(save_result_df[metric])
    save_result_df = pd.concat([save_result_df, row_df])
    save_result_df.to_csv(str(Path(args.data_dir).joinpath('log', args.dataset, server.model_setting_str).joinpath('result.csv')))