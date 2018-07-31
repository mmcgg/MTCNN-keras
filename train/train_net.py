import datetime
import os

import keras.backend.tensorflow_backend as TK
import numpy as np
import tensorflow as tf
from keras.callbacks import TensorBoard, ModelCheckpoint
from keras.losses import categorical_crossentropy
from keras.optimizers import Adam

from mtcnn import p_net
from .config import LABEL_MAP

LOG_DIR = os.path.join(os.path.dirname(__file__), '../logs')
MODES = ['label', 'bbox', 'landmark']

NEGATIVE = TK.constant(LABEL_MAP['0'])
POSITIVE = TK.constant(LABEL_MAP['1'])
PARTIAL = TK.constant(LABEL_MAP['-1'])
LANDMARK = TK.constant(LABEL_MAP['-2'])
num_keep_radio = 0.7


def create_callbacks_model_file(prefix, epochs):
    filename = datetime.datetime.now().strftime('%Y%m%d_%H%M%S.%f')
    log_dir = "{}/{}_{}".format(LOG_DIR, prefix, filename)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    tensor_board = TensorBoard(log_dir=log_dir)
    model_file_path = '{}/{}_{}_{}.h5'.format(log_dir, prefix, epochs, filename)

    checkpoint = ModelCheckpoint(model_file_path, verbose=0, save_weights_only=True)
    return [checkpoint, tensor_board], model_file_path


def cal_mask(label_true, _type='label'):
    def true_func():
        return 0

    def false_func():
        return 1

    label_true_int32 = tf.cast(label_true, dtype=tf.int32)
    if _type == 'label':
        label_filtered = tf.map_fn(lambda x: tf.cond(tf.equal(x[0], x[1]), true_func, false_func), label_true_int32)
    elif _type == 'bbox':
        label_filtered = tf.map_fn(lambda x: tf.cond(tf.equal(x[0], 1), true_func, false_func), label_true_int32)
    elif _type == 'landmark':
        label_filtered = tf.map_fn(lambda x: tf.cond(tf.logical_and(tf.equal(x[0], 1), tf.equal(x[1], 1)),
                                                     false_func, true_func), label_true_int32)
    else:
        raise ValueError('Unknown type of: {} while calculate mask'.format(_type))

    mask = tf.cast(label_filtered, dtype=tf.int32)
    return mask


def label_ohem(label_true, label_pred):
    mask = cal_mask(label_true, 'label')
    label_true1 = tf.boolean_mask(label_true, mask)
    label_pred1 = tf.boolean_mask(label_pred, mask)

    label_loss = categorical_crossentropy(label_true1, label_pred1)

    num = tf.reduce_sum(mask)
    # keep_num = tf.cast(tf.multiply(tf.cast(num, dtype=tf.float32), num_keep_radio), dtype=tf.int32)

    label_loss = label_loss * tf.cast(num, dtype=tf.float32)
    # label_loss = tf.nn.top_k(label_loss, k=keep_num)
    return tf.reduce_mean(label_loss)


def bbox_ohem(label_true, bbox_true, bbox_pred):
    mask = cal_mask(label_true, 'bbox')

    bbox_true1 = tf.boolean_mask(bbox_true, mask, axis=0)
    bbox_pred1 = tf.boolean_mask(bbox_pred, mask, axis=0)

    return tf.losses.mean_squared_error(bbox_true1, bbox_pred1)


def landmark_ohem(label_true, landmark_true, landmark_pred):
    mask = cal_mask(label_true, 'landmark')

    landmark_true1 = tf.boolean_mask(landmark_true, mask)
    landmark_pred1 = tf.boolean_mask(landmark_pred, mask)

    return tf.losses.mean_squared_error(landmark_true1, landmark_pred1)


def p_net_loss(y_true, y_pred):
    labels_true = y_true[:, :2]
    bbox_true = y_true[:, 2:6]
    landmark_true = y_true[:, 6:]

    labels_pred = y_pred[:, :2]
    bbox_pred = y_pred[:, 2:6]
    landmark_pred = y_pred[:, 6:]

    label_loss = label_ohem(labels_true, labels_pred)
    bbox_loss = bbox_ohem(labels_true, bbox_true, bbox_pred)
    landmark_loss = landmark_ohem(labels_true, landmark_true, landmark_pred)

    return label_loss + bbox_loss * 0.5 + landmark_loss * 0.5


def train_p_net_(inputs_image, labels, bboxes, landmarks, batch_size, initial_epoch=0, epochs=1000, lr=0.001,
                 callbacks=None, weights_file=None):
    y = np.concatenate((labels, bboxes, landmarks), axis=1)
    _p_net = p_net(training=True)
    _p_net.summary()
    if weights_file is not None:
        _p_net.load_weights(weights_file)

    _p_net.compile(Adam(lr=lr), loss=p_net_loss, metrics=['accuracy'])
    _p_net.fit(inputs_image, y,
               batch_size=batch_size,
               initial_epoch=initial_epoch,
               epochs=epochs,
               callbacks=callbacks,
               verbose=1)
    return _p_net
