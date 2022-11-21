import os
import copy
import json
import argparse
import time, sys
import numpy as np
import pandas as pd
import opensmile, argparse, pickle, pdb, re

from tqdm import tqdm
from pathlib import Path
from sklearn.model_selection import KFold

sys.path.append(os.path.join(str(Path(os.path.realpath(__file__)).parents[1])))
from partition_manager import partition_manager


if __name__ == '__main__':

    # Argument parser
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw_data_dir",
        type=str,
        default="/media/data/public-data/SER/crema_d/CREMA-D",
        help="Raw data path of CREMA-D data set",
    )
    
    parser.add_argument(
        "--output_partition_path",
        type=str,
        default="/media/data/projects/speech-privacy/fed-multimodal/partition",
        help="Output path of CREMA-D data set",
    )

    parser.add_argument(
        "--setup",
        type=str,
        default="federated",
        help="setup of the experiment: centralized/federated",
    )
    parser.add_argument(
        "--dataset", 
        type=str,
        default="crema_d",
        help="dataset name",
    )
    args = parser.parse_args()

    # save the partition
    output_data_path = Path(args.output_partition_path).joinpath(args.dataset)
    Path.mkdir(output_data_path, parents=True, exist_ok=True)

    # define partition manager
    pm = partition_manager(args)
    
    # fetch all files
    pm.fetch_filelist()
    # fetch all labels
    pm.fetch_label_dict()

    # read demographics
    demo_df = pd.read_csv(str(Path(args.raw_data_dir).joinpath('VideoDemographics.csv')), index_col=0)
    # read ratings
    rating_df = pd.read_csv(str(Path(args.raw_data_dir).joinpath(
        'processedResults', 
        'summaryTable.csv'
    )), index_col=1)
    
    # read client data
    client_data_dict = dict()
    for idx, file_path in enumerate(pm.file_list):
        if '1076_MTI_SAD_XX.wav' in str(file_path): continue
        sentence_file = file_path.parts[-1].split('.wav')[0]
        speaker_id = int(sentence_file.split('_')[0])
        emotion = rating_df.loc[sentence_file, 'MultiModalVote']
        if emotion not in pm.label_dict: continue
        if speaker_id not in client_data_dict:
            client_data_dict[speaker_id] = dict()
        # save data to key
        client_data_dict[speaker_id][str(file_path)] = [
            f'{speaker_id}/{sentence_file}', 
            str(file_path), 
            pm.label_dict[emotion], 
            speaker_id
        ]
        
    # train data
    client_keys = list(client_data_dict.keys())
    client_keys.sort()
    
    # create 5 fold
    kf = KFold(
        n_splits=5, 
        random_state=None, 
        shuffle=False
    )
    # extract partition for each fold
    for fold_idx, split_idx in enumerate(kf.split(client_keys)):
        # save partition dictionary
        partition_dict = dict()
        partition_dict['dev'] = list()
        partition_dict['test'] = list()
        # save data path
        output_data_path = Path(args.output_partition_path).joinpath(
            args.dataset, 
            f'fold{fold_idx+1}'
        )
        Path.mkdir(
            output_data_path, 
            parents=True, 
            exist_ok=True
        )
        
        # train clients, test clients
        train_idx, test_idx = split_idx
        train_clients = [client_keys[idx] for idx in train_idx]
        test_clients = [client_keys[idx] for idx in test_idx]
        
        # iterate clients
        for client_id in train_clients:
            # read client data
            client_dict = copy.deepcopy(client_data_dict[client_id])
            # read client keys
            train_dev_file_id = list(client_dict.keys())
            train_dev_file_id.sort()
            
            # partition train/dev keys
            train_file_id, dev_file_id = pm.split_train_dev(train_dev_file_id)
            # copy to partition data
            partition_dict[client_id] = list()
            for file_id in train_file_id:
                partition_dict[client_id].append(client_data_dict[client_id][file_id])
            for file_id in dev_file_id:
                partition_dict['dev'].append(client_data_dict[client_id][file_id])
        
        # save test files
        for client_id in test_clients:
            # read client data
            client_dict = copy.deepcopy(client_data_dict[client_id])
            # read client keys
            test_file_id = list(client_dict.keys())
            test_file_id.sort()
            # copy to partition data
            for file_id in test_file_id:
                partition_dict['test'].append(client_data_dict[client_id][file_id])
        
        # dump the dictionary
        with open(output_data_path.joinpath(f'partition.json'), "w") as handle:
            json.dump(
                partition_dict, 
                handle
            )
