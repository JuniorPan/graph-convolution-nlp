import os
import sys
from sklearn.externals import joblib
from tensorflow.python import keras as K
import chazutsu
from chariot.storage import Storage
import chariot.transformer as ct
from chariot.preprocessor import Preprocessor
from chariot.feeder import LanguageModelFeeder


class Trainer():

    def __init__(self, root="", lang=None, min_df=5, max_df=sys.maxsize,
                 unknown="<unk>", preprocessor_name="preprocessor", log_dir=""):
        default_root = os.path.join(os.path.dirname(__file__), "../../")
        _root = root if root else default_root

        self.storage = Storage(_root)
        self.preprocessor_name = preprocessor_name
        self.__log_dir = log_dir
        self.preprocessor = Preprocessor(
                                text_transformers=[
                                    ct.text.UnicodeNormalizer(),
                                    ct.text.LowerNormalizer()
                                ],
                                tokenizer=ct.Tokenizer(lang=lang),
                                vocabulary=ct.Vocabulary(
                                            min_df=min_df, max_df=max_df,
                                            unknown=unknown))

        if os.path.exists(self.preprocessor_path):
            self.preprocessor = joblib.load(self.preprocessor_path)

    @property
    def preprocessor_path(self):
        path = "interim/{}.pkl".format(self.preprocessor_name)
        return self.storage.data_path(path)

    @property
    def _log_dir(self):
        folder = "/" + self.__log_dir if self.__log_dir else ""
        log_dir = "log{}".format(folder)
        if not os.path.exists(self.storage.data_path(log_dir)):
            os.mkdir(self.storage.data_path(log_dir))

        return log_dir

    @property
    def log_dir(self):
        return self.storage.data_path(self._log_dir)

    @property
    def model_path(self):
        return self.storage.data_path(self._log_dir + "/model.h5")

    @property
    def tensorboard_dir(self):
        return self.storage.data_path(self._log_dir)

    def download(self):
        download_dir = self.storage.data_path("raw")
        r = chazutsu.datasets.WikiText2().download(download_dir)
        return r

    def build(self, data_kind="train", save=True):
        r = self.download()
        data = r.train_data()
        if data_kind == "test":
            data = r.test_data()
        elif data_kind == "valid":
            data = r.valid_data()

        print("Building Dictionary from {} data...".format(data_kind))
        self.preprocessor.fit(data)
        if save:
            joblib.dump(self.preprocessor, self.preprocessor_path)
        print("Done!")

    def train(self, model, data_kind="train", batch_size=32, sequence_length=8, epochs=50, 
              build_force=False):
        if not os.path.exists(self.preprocessor_path) and not build_force:
            self.build(data_kind)

        r = self.download()
        step_generators = {"train": {}, "test": {}}

        for k in step_generators:
            if k == "train":
                data = r.train_data() if data_kind == "train" else r.valid_data()
            else:
                data = r.test_data()

            spec = {"sentence": ct.formatter.ShiftGenerator()}
            feeder = LanguageModelFeeder(spec)
            data = self.preprocessor.transform(data)
            step, generator = feeder.make_generator(
                                data, batch_size=batch_size,
                                sequence_length=sequence_length,
                                sequencial=False)

            step_generators[k]["g"] = generator
            step_generators[k]["s"] = step

        callbacks = [K.callbacks.ModelCheckpoint(self.model_path, save_best_only=True),
                     K.callbacks.TensorBoard(self.tensorboard_dir)]

        metrics = model.fit_generator(
                    step_generators["train"]["g"](),
                    step_generators["train"]["s"],
                    validation_data=step_generators["test"]["g"](),
                    validation_steps=step_generators["test"]["s"],
                    epochs=epochs,
                    callbacks=callbacks)

        return metrics

    def generate_text(seed_text, model, sequence_length=10, iteration=20):
        preprocessed = self.preprocessor.transform([seed_text])[0]

        def pad_sequence(tokens, length):
            if len(tokens) < length:
                pad_size = length - len(tokens)
                return tokens + [self.preprocessor.vocabulary.pad] * pad_size
            elif len(tokens) > length:
                return tokens[-length:]
            else:
                return tokens

        for _ in range(iteration):
            x = pad_sequence(preprocessed, sequence_length)
            y = model.predict([x])[0]
            w = np.random.choice(np.arange(len(y)), 1, p=y)[0]
            preprocessed.append(w)
        
        decoded = self.preprocessor.inverse_transform([preprocessed])
        text = " ".join(decoded[0])

        return text