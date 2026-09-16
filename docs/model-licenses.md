# Model licenses

Model code and model weights are separate from the Apache-2.0 project source.

The downloader fetches these fixed OpenCV Zoo objects by immutable repository revision and verifies the SHA-256 digest before use.

| Adapter | File | Revision | SHA-256 | Upstream weight/code license |
| --- | --- | --- | --- | --- |
| YuNet detector | `face_detection_yunet_2023mar.onnx` | `47534e27c9851bb1128ccc0102f1145e27f23f98` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | MIT, OpenCV Zoo model directory |
| SFace encoder | `face_recognition_sface_2021dec.onnx` | `47534e27c9851bb1128ccc0102f1145e27f23f98` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | Apache-2.0, OpenCV Zoo model directory |

Sources:

- https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet
- https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface
- https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/LICENSE

The model files are not included in this repository. Review upstream terms before redistribution or commercial use.
