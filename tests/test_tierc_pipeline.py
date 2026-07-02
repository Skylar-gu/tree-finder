"""Tier C method A pipeline + scoring/reach integration (spec §5.2, §5.3, §7)."""

from score.climbability import score_tree
from score.reach import ReachParams, reach_match
from tierC.backends import ConstantDepth, SyntheticTrunkSegmenter
from tierC.camera import Camera
from tierC.mapillary import MapillaryImage
from tierC.pipeline import BRANCH_GATE, gated_branches, run_monocular, streetcv_feature


def _cam(is_pano=False):
    return Camera(fx=1000.0, fy=1000.0, cx=400, cy=500, width=800, height=1000, is_pano=is_pano)


def _mly(is_pano=False, q=0.8):
    return MapillaryImage(
        image_id="img1", lon=-122.0, lat=45.0, is_pano=is_pano,
        camera_parameters=[0.5], compass_angle=0, captured_at=0, quality_score=q,
    )


def test_monocular_produces_dbh_and_gated_ladder():
    out = run_monocular(
        image=(800, 1000), camera=_cam(),
        depth=ConstantDepth(8.0), segmenter=SyntheticTrunkSegmenter(),
        mly_image=_mly(q=0.9),
    )
    assert out.dbh_cm_streetcv.value is not None
    assert out.dbh_cm_streetcv.band > 0
    assert out.tierC_confidence <= 0.70          # capped: coarse by construction
    assert out.lowest_branch_h_m.value is not None
    assert out.attribution["license"] == "CC-BY-SA 4.0"


def test_pano_frame_yields_empty_low_conf_output():
    out = run_monocular(
        image=(800, 1000), camera=_cam(is_pano=True),
        depth=ConstantDepth(8.0), segmenter=SyntheticTrunkSegmenter(),
        mly_image=_mly(is_pano=True),
    )
    assert out.tierC_confidence == 0.0
    assert out.branch_ladder == []
    assert out.dbh_cm_streetcv.value is None
    assert any("is_pano" in n for n in out.notes)


def test_low_confidence_withholds_branch_ladder():
    # Poor segmentation + poor frame quality -> below the branch gate.
    seg = SyntheticTrunkSegmenter(seg_quality=0.05)
    out = run_monocular(
        image=(800, 1000), camera=_cam(),
        depth=ConstantDepth(8.0), segmenter=seg, mly_image=_mly(q=0.0),
    )
    assert out.tierC_confidence < BRANCH_GATE
    assert out.branch_ladder == []               # withheld
    assert gated_branches(out) == []
    assert streetcv_feature(out) is None         # keeps w_c dormant


def test_streetcv_feature_rewards_low_first_branch():
    out = run_monocular(
        image=(800, 1000), camera=_cam(),
        depth=ConstantDepth(8.0), segmenter=SyntheticTrunkSegmenter(),
        mly_image=_mly(q=0.9),
    )
    f = streetcv_feature(out)
    assert f is not None and 0.0 <= f <= 1.0


def test_measured_ladder_beats_form_guess_and_carries_tierc_confidence():
    out = run_monocular(
        image=(800, 1000), camera=_cam(),
        depth=ConstantDepth(6.0), segmenter=SyntheticTrunkSegmenter(),
        mly_image=_mly(q=0.9),
    )
    branches = gated_branches(out)
    assert branches, "expected a gated measured ladder"
    p = ReachParams(h_m=1.8)
    measured = reach_match(p, branches=branches, ladder_confidence=out.tierC_confidence)
    assert measured.is_measured_ladder is True
    assert measured.mode == "measured_ladder"
    # Confidence reflects the COARSE Tier C measurement, not the 0.9 LiDAR default.
    assert measured.confidence == round(out.tierC_confidence, 3)
    assert measured.confidence < 0.9

    guess = reach_match(p, scaffold_form=0.6, f_dbh=0.5)
    assert guess.is_measured_ladder is False


def test_tierc_f_streetcv_flows_into_score_and_activates_w_c():
    out = run_monocular(
        image=(800, 1000), camera=_cam(),
        depth=ConstantDepth(4.0), segmenter=SyntheticTrunkSegmenter(),
        mly_image=_mly(q=0.9),
    )
    f = streetcv_feature(out)
    base = score_tree(genus="Quercus", dbh_cm=55)
    withc = score_tree(genus="Quercus", dbh_cm=55, f_streetcv=f)
    # Street-geometry signal recorded in provenance and its weight now active.
    assert "street_geometry" in withc.provenance["signals"]
    agg = next(w for w in withc.why_scored if w["feature"] == "_aggregate")
    assert agg["weights_used"]["w_streetcv"] > 0
    assert "street_geometry" not in base.provenance["signals"]
