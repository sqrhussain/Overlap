import os
import logging; logging.basicConfig(level=logging.WARNING)
import numpy as np
import pandas as pd
from itertools import product
from tqdm import tqdm
import time
import gc
from keras import backend as K

from data_generator import DataGenerator
from myutils import Utils

class RunPipeline():
    def __init__(self, suffix:str=None, generate_duplicates=False, n_samples_threshold=1000,
                 realistic_synthetic_mode=None, parallel='proposed', architecture=None, loss_name=None,
                 adsd_batch_size=256, seed=0):
        '''
        generate_duplicates: whether to generate duplicated samples when sample size is too small
        n_samples_threshold: threshold for generating the above duplicates
        '''

        # my utils function
        self.utils = Utils()

        # global parameters
        self.generate_duplicates = generate_duplicates
        self.n_samples_threshold = n_samples_threshold
        self.realistic_synthetic_mode = realistic_synthetic_mode

        # the suffix of all saved files
        if parallel != 'proposed':
            self.suffix = suffix + '_baseline_' + parallel + '_' + 'duplicates(' + str(generate_duplicates) + ')_' + 'synthetic(' + str(realistic_synthetic_mode) + ')'
        else:
            assert architecture is not None
            self.suffix = suffix + '_' + parallel + '_' + architecture + '_' + loss_name + '_' + 'duplicates(' + str(generate_duplicates) + ')_' + 'synthetic(' + str(realistic_synthetic_mode) + ')'

        # data generator instantiation
        self.data_generator = DataGenerator(generate_duplicates=self.generate_duplicates,
                                            n_samples_threshold=self.n_samples_threshold)

        # ratio of labeled anomalies
        self.rla_list = [0.05, 0.10, 0.20]
        # seed list
        self.seed_list = list(np.arange(5) + 1)

        self.parallel = parallel
        self.architecture = architecture
        self.loss_name = loss_name

        # model dict
        self.model_dict = {}

        if self.parallel == 'unsup':
            from baseline.PyOD import PYOD

            self.model_dict['IForest'] = PYOD
            self.model_dict['ECOD'] = PYOD
            self.model_dict['DeepSVDD'] = PYOD # need tensorflow 2.0+

        elif self.parallel == 'semi':
            from baseline.GANomaly.run import GANomaly
            from baseline.DeepSAD.src.run import DeepSAD
            from baseline.REPEN.run import REPEN
            from baseline.DevNet.run import DevNet
            from baseline.PReNet.run import PReNet
            from baseline.FEAWAD.run import FEAWAD

            self.model_dict['GANomaly'] = GANomaly
            self.model_dict['DeepSAD'] = DeepSAD
            self.model_dict['REPEN'] = REPEN
            self.model_dict['DevNet'] = DevNet
            self.model_dict['PReNet'] = PReNet
            self.model_dict['FEAWAD'] = FEAWAD

        elif self.parallel == 'sup':
            from baseline.FS.run import fs
            from baseline.FTTransformer.run import FTTransformer

            self.model_dict['FS'] = fs
            self.model_dict['ResNet'] = FTTransformer
            self.model_dict['FTTransformer'] = FTTransformer

        elif self.parallel == 'proposed':
            from baseline.ADSD.run import adsd
            self.model_dict['ADSD'] = adsd(seed=seed, batch_size=adsd_batch_size)

        else:
            raise NotImplementedError

    # dataset filter for delelting those datasets that do not satisfy the experimental requirement
    def dataset_filter(self):
        # dataset list in the current folder
        dataset_list_org = [os.path.splitext(_)[0] for _ in os.listdir(os.path.join(os.getcwd(), 'datasets'))
                            if os.path.splitext(_)[-1] == '.npz']

        # 将不符合标准的数据集筛除
        dataset_list = []
        dataset_size = []

        for dataset in dataset_list_org:
            add = True
            for seed in self.seed_list:
                self.data_generator.seed = seed
                self.data_generator.dataset = dataset
                data = self.data_generator.generator(la=1.00)

                if not self.generate_duplicates and len(data['y_train']) + len(data['y_test']) < self.n_samples_threshold:
                    add = False
                else:
                    # rla模式中只要训练集labeled anomalies个数超过0即可
                    if sum(data['y_train']) > 0:
                        pass

                    else:
                        add = False

            if add:
                dataset_list.append(dataset)
                dataset_size.append(len(data['y_train']) + len(data['y_test']))
            else:
                print(f"数据集{dataset}被移除")

        # 按照数据集大小进行排序
        dataset_list = [dataset_list[_] for _ in np.argsort(np.array(dataset_size))]

        return dataset_list

    # model fitting function
    def model_fit(self, x_train, y_train, x_test, ratio):
        try:
            # model initialization, if model weights are saved, the save_suffix should be specified
            if self.model_name in ['DevNet', 'FEAWAD', 'REPEN']:
                self.clf = self.clf(seed=self.seed, model_name=self.model_name, save_suffix=self.suffix)
            elif self.model_name == 'ADSD':
                self.clf = self.clf(seed=self.seed, model_name=self.model_name, architecture=self.architecture, loss_name=self.loss_name)
            else:
                raise NotImplementedError

        except Exception as error:
            print(f'Error in model initialization. Model:{self.model_name}, Error: {error}')
            pass

        # try:
        # model fitting, currently most of models are implemented to output the anomaly score
        # fitting
        score_test = self.clf.fit2test(x_train, y_train, x_test)

        K.clear_session()  # 实际发现代码会越跑越慢,原因是keras中计算图会叠加,需要定期清除

        del self.clf
        gc.collect()

        # except Exception as error:
        #     print(f'Error in model fitting. Model:{self.model_name}, Error: {error}')
        #     pass

        return score_test


    # run the experiment
    def run(self, x_train, y_train, x_test, ratio, seed):
        # ratio = sum(self.data['y_test']) / len(self.data['y_test'])

        self.seed = seed

        self.model_name = 'ADSD'
        self.clf = self.model_dict[self.model_name]

        # fit model
        result = self.model_fit(x_train, y_train, x_test, ratio)

        return result



def run_ADSD(x_train, y_train, x_test, ratio, seed, batch_size):
    # run the experment
    pipeline = RunPipeline(suffix='ADSD_no_ensemble', parallel='proposed', architecture='MLP', loss_name='ADSD',
                           generate_duplicates=True, n_samples_threshold=1000, realistic_synthetic_mode=None,
                           adsd_batch_size=batch_size, seed=seed)
    pipeline.run(x_train, y_train, x_test, ratio, seed)

#
# import pandas as pd
#
# x_train = pd.read_csv("tmp/x_train.csv")
# y_train = pd.read_csv("tmp/y_train.csv")
# x_test = pd.read_csv("tmp/x_test.csv")
#
# run_ADSD(x_train.to_numpy(), y_train.to_numpy()[:,1].astype(float), x_test.to_numpy(), ratio=.04651163, seed=0, batch_size=10)
