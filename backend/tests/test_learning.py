"""Model contract checks; geometric correctness is separately validated."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomwise.learning import MODEL_PATH, model_status, refine_scene, torch, make_features


def fixture():
    return {"id":"learning-contract","version":0,"room":{"width":5,"depth":4,"height":2.7,
            "polygon":None,"door":{"wall":"south","offset":.3,"width":.9,"clearance":.9},"windows":[]},
            "items":[{"id":"bed-a","label":"旧床","category":"double_bed","width":1.8,"depth":2,
                      "height":.55,"x":2.5,"z":2.5,"rotation":17,"locked":True,"keep":True,
                      "source":"brought","assetUrl":None,"photoUrl":"/photo-a.jpg"},
                     {"id":"wardrobe-b","label":"房内柜","category":"wardrobe","width":1.2,"depth":.6,
                      "height":2,"x":4,"z":2,"rotation":90,"locked":False,"keep":True,"source":"existing"},
                     {"id":"rug-c","label":"地毯","category":"rug","width":2,"depth":2,"height":.01,
                      "x":1,"z":1,"rotation":0,"locked":False,"keep":True,"source":"existing"}],
            "preferences":[{"kind":"min_move","itemId":"wardrobe-b"}]}


@unittest.skipUnless(torch is not None and MODEL_PATH.exists(), "real checkpoint not trained yet")
class LearningContractTests(unittest.TestCase):
    def test_no_inplace_edit_and_identity_sizes_locks(self):
        scene=fixture(); original=copy.deepcopy(scene)
        output=refine_scene(scene)
        self.assertEqual(scene,original)
        self.assertEqual(output["room"],original["room"])
        self.assertEqual(output["preferences"],original["preferences"])
        self.assertEqual(output["items"][0],original["items"][0])
        self.assertEqual(output["items"][2],original["items"][2])
        for item,before in zip(output["items"],original["items"]):
            protected={k:v for k,v in item.items() if k not in ("x","z","rotation")}
            expected={k:v for k,v in before.items() if k not in ("x","z","rotation")}
            self.assertEqual(protected,expected)
            self.assertTrue(np.isfinite([item["x"],item["z"],item["rotation"]]).all())

    def test_permutation_equivariance(self):
        scene=fixture(); permuted=copy.deepcopy(scene)
        permuted["items"]=list(reversed(permuted["items"]))
        a=refine_scene(scene);b=refine_scene(permuted)
        by_id={item["id"]:item for item in b["items"]}
        for item in a["items"]:
            for key in ("x","z","rotation"):
                self.assertAlmostEqual(item[key],by_id[item["id"]][key],places=3)

    def test_status_describes_actual_checkpoint(self):
        status=model_status()
        self.assertTrue(status["available"])
        self.assertTrue(status["training"]["trained"])
        self.assertGreater(status["training"]["steps"],0)


class EncoderTests(unittest.TestCase):
    def test_padding_and_units(self):
        pos=np.zeros((1,2,2),np.float32);pos[0,0]=[3,-3]
        mask=np.array([[True,False]])
        features,padding=make_features(pos,np.zeros((1,2)),np.ones((1,2,3))*3,
                                      np.array([[7,-1]]),np.array([[True,False]]),mask,
                                      np.zeros((1,12,2)),np.array([[6,6]]))
        np.testing.assert_equal(features[0,0,:2],[1,-1])
        np.testing.assert_equal(features[0,0,4:7],[1,1,1])
        self.assertEqual(features[0,0,7+7],1)
        self.assertEqual(features[0,0,26],1)
        self.assertTrue(padding[0,1]);self.assertFalse(padding[0,0])


if __name__=="__main__":unittest.main()
