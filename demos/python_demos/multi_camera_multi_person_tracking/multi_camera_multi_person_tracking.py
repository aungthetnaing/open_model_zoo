"""
 Copyright (c) 2019 Intel Corporation
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

import argparse
import time
import queue
from threading import Thread
import json
import logging as log
import sys

import cv2 as cv

from utils.network_wrappers import Detector, VectorCNN
from mc_tracker.mct import MultiCameraTracker
from utils.misc import read_py_config
from utils.video import MulticamCapture
from utils.visualization import visualize_multicam_detections, draw_detections
from openvino.inference_engine import IECore # pylint: disable=import-error,E0611

log.basicConfig(stream=sys.stdout, level=log.DEBUG)

class SingleCameraRunThreadBody:
    def __init__(self, capture, tracker, detector, index):
        self.process = True
        self.capture = capture
        self.tracker = tracker
        self.camIndex = index
        self.detector = detector

    def __call__(self):
        thread_body = FramesThreadBodySingle(self.capture, self.camIndex)
        frames_thread = Thread(target=thread_body)
        frames_thread.start()
        while cv.waitKey(1) != 27 and thread_body.process and self.process:
            start = time.time()
            try:
                frame = thread_body.frames_queue.get_nowait()
            except queue.Empty:
                frame = None

            if frame is None:
                continue
            start2 = time.time()
            all_detections = self.detector.get_detection(frame)
            diff = time.time() - start2
            self.tracker.process_single_frame(frame, all_detections, self.camIndex)
            tracked_objects = self.tracker.get_tracked_objects_singlecam(self.camIndex)
       
            fps = round(1 / (time.time() - start) - diff, 1)
            draw_detections(frame, tracked_objects)
            win_name = 'cam ' + str(self.camIndex)
            cv.namedWindow(win_name, cv.WINDOW_NORMAL) 
            cv.imshow(win_name, frame)
        thread_body.process = False
        frames_thread.join()



        
class FramesThreadBody:
    def __init__(self, capture, max_queue_length=2):
        self.process = True
        self.frames_queue = queue.Queue()
        self.capture = capture
        self.max_queue_length = max_queue_length

    def __call__(self):
        while self.process:
            if self.frames_queue.qsize() > self.max_queue_length:
                time.sleep(0.1)
            has_frames, frames = self.capture.get_frames()
            if not has_frames and self.frames_queue.empty():
                self.process = False
                break
            if has_frames:
                self.frames_queue.put(frames)

class FramesThreadBodySingle:
    def __init__(self, capture, index, max_queue_length=2):
        self.process = True
        self.frames_queue = queue.Queue()
        self.capture = capture
        self.max_queue_length = max_queue_length
        self.camIndex = index

    def __call__(self):
        while self.process:
            if self.frames_queue.qsize() > self.max_queue_length:
                time.sleep(0.1)
            has_frames, frames = self.capture.get_frame(self.camIndex)
            if not has_frames and self.frames_queue.empty():
                self.process = False
                break
            if has_frames:
                self.frames_queue.put(frames)


def run(params, capture, detector, reid):
    win_name = 'Multi camera tracking'
    config = {}
    if len(params.config):
        config = read_py_config(params.config)

    tracker = MultiCameraTracker(capture.get_num_sources(), reid, **config)
    thread_bodies = []
    frames_threads = []
    for i in range(capture.get_num_sources()):
        thread_body = SingleCameraRunThreadBody(capture, tracker, detector, i)
        thread_bodies.append(thread_body)
        frames_thread = Thread(target=thread_body)
        frames_thread.start()
        frames_threads.append(frames_thread)
    for cur_thread in frames_threads:
        cur_thread.join()



def main():
    """Prepares data for the person recognition demo"""
    parser = argparse.ArgumentParser(description='Multi camera multi person \
                                                  tracking live demo script')
    parser.add_argument('-i', type=str, nargs='+', help='Input sources (indexes \
                        of cameras or paths to video files)', required=True)

    parser.add_argument('-m', '--m_detector', type=str, required=True,
                        help='Path to the person detection model')
    parser.add_argument('--t_detector', type=float, default=0.6,
                        help='Threshold for the person detection model')

    parser.add_argument('--m_reid', type=str, required=True,
                        help='Path to the person reidentification model')

    parser.add_argument('--output_video', type=str, default='', required=False)
    parser.add_argument('--config', type=str, default='', required=False)
    parser.add_argument('--history_file', type=str, default='', required=False)

    parser.add_argument('-d', '--device', type=str, default='CPU')
    parser.add_argument('-l', '--cpu_extension',
                        help='MKLDNN (CPU)-targeted custom layers.Absolute \
                              path to a shared library with the kernels impl.',
                             type=str, default=None)

    args = parser.parse_args()

    capture = MulticamCapture(args.i)
    ie = IECore()

    person_detector = Detector(ie, args.m_detector, args.t_detector,
                               'CPU', args.cpu_extension,
                               capture.get_num_sources())
    if args.m_reid:
        person_recognizer = VectorCNN(ie, args.m_reid, args.device)
    else:
        person_recognizer = None
    run(args, capture, person_detector, person_recognizer)
    log.info('Demo finished successfully')


if __name__ == '__main__':
    main()
