import math
import numbers
import warnings
from typing import Any, Dict, Tuple

import PIL.Image
import torch
from torchvision.prototype import features
from torchvision.prototype.transforms import Transform, functional as F

from ._utils import query_image


class RandomErasing(Transform):
    _DISPATCHER = F.erase
    _FAIL_TYPES = {PIL.Image.Image, features.BoundingBox, features.SegmentationMask}

    def __init__(
        self,
        p: float = 0.5,
        scale: Tuple[float, float] = (0.02, 0.33),
        ratio: Tuple[float, float] = (0.3, 3.3),
        value: float = 0,
    ):
        super().__init__()
        if not isinstance(value, (numbers.Number, str, tuple, list)):
            raise TypeError("Argument value should be either a number or str or a sequence")
        if isinstance(value, str) and value != "random":
            raise ValueError("If value is str, it should be 'random'")
        if not isinstance(scale, (tuple, list)):
            raise TypeError("Scale should be a sequence")
        if not isinstance(ratio, (tuple, list)):
            raise TypeError("Ratio should be a sequence")
        if (scale[0] > scale[1]) or (ratio[0] > ratio[1]):
            warnings.warn("Scale and ratio should be of kind (min, max)")
        if scale[0] < 0 or scale[1] > 1:
            raise ValueError("Scale should be between 0 and 1")
        if p < 0 or p > 1:
            raise ValueError("Random erasing probability should be between 0 and 1")
        # TODO: deprecate p in favor of wrapping the transform in a RandomApply
        self.p = p
        self.scale = scale
        self.ratio = ratio
        self.value = value

    def _get_params(self, sample: Any) -> Dict[str, Any]:
        image = query_image(sample)
        img_h, img_w = F.get_image_size(image)
        img_c = F.get_image_num_channels(image)

        if isinstance(self.value, (int, float)):
            value = [self.value]
        elif isinstance(self.value, str):
            value = None
        elif isinstance(self.value, tuple):
            value = list(self.value)
        else:
            value = self.value

        if value is not None and not (len(value) in (1, img_c)):
            raise ValueError(
                f"If value is a sequence, it should have either a single value or {img_c} (number of input channels)"
            )

        area = img_h * img_w

        log_ratio = torch.log(torch.tensor(self.ratio))
        for _ in range(10):
            erase_area = area * torch.empty(1).uniform_(self.scale[0], self.scale[1]).item()
            aspect_ratio = torch.exp(
                torch.empty(1).uniform_(
                    log_ratio[0],  # type: ignore[arg-type]
                    log_ratio[1],  # type: ignore[arg-type]
                )
            ).item()

            h = int(round(math.sqrt(erase_area * aspect_ratio)))
            w = int(round(math.sqrt(erase_area / aspect_ratio)))
            if not (h < img_h and w < img_w):
                continue

            if value is None:
                v = torch.empty([img_c, h, w], dtype=torch.float32).normal_()
            else:
                v = torch.tensor(value)[:, None, None]

            i = torch.randint(0, img_h - h + 1, size=(1,)).item()
            j = torch.randint(0, img_w - w + 1, size=(1,)).item()
            break
        else:
            i, j, h, w, v = 0, 0, img_h, img_w, image

        return dict(zip("ijhwv", (i, j, h, w, v)))

    def _transform(self, input: Any, params: Dict[str, Any]) -> Any:
        if torch.rand(1) >= self.p:
            return input

        return super()._transform(input, params)


class RandomMixup(Transform):
    _DISPATCHER = F.mixup
    _FAIL_TYPES = {features.BoundingBox, features.SegmentationMask}

    def __init__(self, *, alpha: float) -> None:
        super().__init__()
        self.alpha = alpha
        self._dist = torch.distributions.Beta(torch.tensor([alpha]), torch.tensor([alpha]))

    def _get_params(self, sample: Any) -> Dict[str, Any]:
        return dict(lam=float(self._dist.sample(())))


class RandomCutmix(Transform):
    _DISPATCHER = F.cutmix
    _FAIL_TYPES = {features.BoundingBox, features.SegmentationMask}

    def __init__(self, *, alpha: float) -> None:
        super().__init__()
        self.alpha = alpha
        self._dist = torch.distributions.Beta(torch.tensor([alpha]), torch.tensor([alpha]))

    def _get_params(self, sample: Any) -> Dict[str, Any]:
        lam = float(self._dist.sample(()))

        image = query_image(sample)
        H, W = F.get_image_size(image)

        r_x = torch.randint(W, ())
        r_y = torch.randint(H, ())

        r = 0.5 * math.sqrt(1.0 - lam)
        r_w_half = int(r * W)
        r_h_half = int(r * H)

        x1 = int(torch.clamp(r_x - r_w_half, min=0))
        y1 = int(torch.clamp(r_y - r_h_half, min=0))
        x2 = int(torch.clamp(r_x + r_w_half, max=W))
        y2 = int(torch.clamp(r_y + r_h_half, max=H))
        box = (x1, y1, x2, y2)

        lam_adjusted = float(1.0 - (x2 - x1) * (y2 - y1) / (W * H))

        return dict(box=box, lam_adjusted=lam_adjusted)
