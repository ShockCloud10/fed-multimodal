# Author: Tiantian Feng
# USC SAIL lab, tiantiaf@usc.edu
import pdb
import glob
import torch
import random
import pickle
import os, sys
import logging
import argparse
import opensmile
import torchaudio

import numpy as np
import os.path as osp

from tqdm import tqdm
from pathlib import Path

sys.path.append(os.path.join(str(Path(os.path.realpath(__file__)).parents[1])))
from feature_manager import feature_manager

# Define logging console
import logging
logging.basicConfig(
    format='%(asctime)s %(levelname)-3s ==> %(message)s', 
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)


def parse_args():
    parser = argparse.ArgumentParser(description='Extract audio features')
    parser.add_argument(
        '--raw_data_dir',
        default='/media/data/public-data/SER/crema_d/CREMA-D', 
        type=str,
        help='source data directory'
    )

    parser.add_argument(
        '--output_dir', 
        default='/media/data/projects/speech-privacy/fed-multimodal/',
        type=str, 
        help='output feature directory'
    )

    parser.add_argument(
        '--feature_type', 
        default='mfcc',
        type=str, 
        help='output feature name'
    )

    parser.add_argument(
        "--dataset", 
        default="crema_d"
    )
    args = parser.parse_args()

    return args


if __name__ == '__main__':
    # read args
    args = parse_args()
    for fold_idx in range(1, 6):
        output_data_path = Path(args.output_dir).joinpath(
            'feature', 
            'audio', 
            args.feature_type, 
            args.dataset,
            f'fold{fold_idx}'
        )
        Path.mkdir(
            output_data_path, 
            parents=True, 
            exist_ok=True
        )
        
        # initialize feature processer
        fm = feature_manager(args)
        
        # fetch all files for processing
        partition_dict = fm.fetch_partition(
            fold_idx=fold_idx,
            file_ext="json"
        )
        logging.info(f'Reading audio from folder: {args.raw_data_dir}')
        logging.info(f'Total number of clients found: {len(partition_dict.keys())}')
        
        # extract data
        for client in partition_dict:
            if Path.exists(output_data_path.joinpath(f'{client}.pkl')) == True: continue
            data_dict = partition_dict[client].copy()
            # normal client case each speaker is a client
            logging.info(f'Process data for {client}')
            if client not in ['dev', 'test']:
                speaker_data = list()
                for idx in tqdm(range(len(data_dict))):
                    file_path = data_dict[idx][1]
                    features = fm.extract_mfcc_features(
                        audio_path=file_path,
                        frame_length=25,
                        frame_shift=10,
                        max_len=600,
                        en_znorm=False
                    )
                    data_dict[idx][-1] = features
                    speaker_data = features if len(speaker_data) == 0 else np.append(speaker_data, features, axis=0)
                # normalize speaker data
                speaker_mean, speaker_std = np.mean(speaker_data, axis=0), np.std(speaker_data, axis=0)
                for idx in range(len(data_dict)):
                    data_dict[idx][-1] = (data_dict[idx][-1] - speaker_mean) / (speaker_std + 1e-5)
            else:
                # find speakers first and its data idx
                speaker_dict = dict()
                for idx in range(len(data_dict)):
                    speaker_id = data_dict[idx][3]
                    if speaker_id not in speaker_dict:
                        speaker_dict[speaker_id] = list()
                    speaker_dict[speaker_id].append(idx)
                
                # iterate over speakers
                for speaker_id in tqdm(speaker_dict):
                    speaker_data = list()
                    for idx in speaker_dict[speaker_id]:
                        file_path = data_dict[idx][1]
                        features = fm.extract_mfcc_features(
                            audio_path=file_path,
                            frame_length=25,
                            frame_shift=10,
                            max_len=600,
                            en_znorm=False
                        )
                        data_dict[idx][-1] = features
                        speaker_data = features if len(speaker_data) == 0 else np.append(speaker_data, features, axis=0)
                    # normalize speaker data
                    speaker_mean, speaker_std = np.mean(speaker_data, axis=0), np.std(speaker_data, axis=0)
                    for idx in speaker_dict[speaker_id]:
                        data_dict[idx][-1] = (data_dict[idx][-1] - speaker_mean) / (speaker_std + 1e-5)

            # pdb.set_trace()
            # saving features
            with open(str(output_data_path.joinpath(f'{client}.pkl')), 'wb') as handle:
                pickle.dump(
                    data_dict, 
                    handle, 
                    protocol=pickle.HIGHEST_PROTOCOL
                )

