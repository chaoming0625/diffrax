from collections.abc import Callable
from typing import ClassVar, Optional

import brainunit as u
import jax
import numpy as np
from jaxtyping import Array, PyTree, Shaped

from .base import vector_tree_dot
from .runge_kutta import AbstractERK, ButcherTableau
from .._custom_types import RealScalarLike, Y
from .._local_interpolation import AbstractLocalInterpolation
from .._misc import linear_rescale

_tsit5_tableau = ButcherTableau(
    a_lower=(
        np.array([161 / 1000]),
        np.array(
            [
                -0.8480655492356988544426874250230774675121177393430391537369234245294192976164141156943e-2,
                # noqa: E501
                0.3354806554923569885444268742502307746751211773934303915373692342452941929761641411569,  # noqa: E501
            ]
        ),
        np.array(
            [
                2.897153057105493432130432594192938764924887287701866490314866693455023795137503079289,  # noqa: E501
                -6.359448489975074843148159912383825625952700647415626703305928850207288721235210244366,  # noqa: E501
                4.362295432869581411017727318190886861027813359713760212991062156752264926097707165077,  # noqa: E501
            ]
        ),
        np.array(
            [
                5.325864828439256604428877920840511317836476253097040101202360397727981648835607691791,  # noqa: E501
                -11.74888356406282787774717033978577296188744178259862899288666928009020615663593781589,  # noqa: E501
                7.495539342889836208304604784564358155658679161518186721010132816213648793440552049753,  # noqa: E501
                -0.9249506636175524925650207933207191611349983406029535244034750452930469056411389539635e-1,
                # noqa: E501
            ]
        ),
        np.array(
            [
                5.861455442946420028659251486982647890394337666164814434818157239052507339770711679748,  # noqa: E501
                -12.92096931784710929170611868178335939541780751955743459166312250439928519268343184452,  # noqa: E501
                8.159367898576158643180400794539253485181918321135053305748355423955009222648673734986,  # noqa: E501
                -0.7158497328140099722453054252582973869127213147363544882721139659546372402303777878835e-1,
                # noqa: E501
                -0.2826905039406838290900305721271224146717633626879770007617876201276764571291579142206e-1,
                # noqa: E501
            ]
        ),
        np.array(
            [
                0.9646076681806522951816731316512876333711995238157997181903319145764851595234062815396e-1,
                # noqa: E501
                1 / 100,
                0.4798896504144995747752495322905965199130404621990332488332634944254542060153074523509,  # noqa: E501
                1.379008574103741893192274821856872770756462643091360525934940067397245698027561293331,  # noqa: E501
                -3.290069515436080679901047585711363850115683290894936158531296799594813811049925401677,  # noqa: E501
                2.324710524099773982415355918398765796109060233222962411944060046314465391054716027841,  # noqa: E501
            ]
        ),
    ),
    b_sol=np.array(
        [
            0.9646076681806522951816731316512876333711995238157997181903319145764851595234062815396e-1,  # noqa: E501
            1 / 100,
            0.4798896504144995747752495322905965199130404621990332488332634944254542060153074523509,  # noqa: E501
            1.379008574103741893192274821856872770756462643091360525934940067397245698027561293331,  # noqa: E501
            -3.290069515436080679901047585711363850115683290894936158531296799594813811049925401677,  # noqa: E501
            2.324710524099773982415355918398765796109060233222962411944060046314465391054716027841,  # noqa: E501
            0.0,
        ]
    ),
    b_error=np.array(
        [
            0.9646076681806522951816731316512876333711995238157997181903319145764851595234062815396e-1  # noqa: E501
            - 0.9468075576583945807478876255758922856117527357724631226139574065785592789071067303271e-1,  # noqa: E501
            1 / 100
            - 0.9183565540343253096776363936645313759813746240984095238905939532922955247253608687270e-2,  # noqa: E501
            0.4798896504144995747752495322905965199130404621990332488332634944254542060153074523509  # noqa: E501
            - 0.4877705284247615707855642599631228241516691959761363774365216240304071651579571959813,  # noqa: E501
            1.379008574103741893192274821856872770756462643091360525934940067397245698027561293331  # noqa: E501
            - 1.234297566930478985655109673884237654035539930748192848315425833500484878378061439761,  # noqa: E501
            -3.290069515436080679901047585711363850115683290894936158531296799594813811049925401677  # noqa: E501
            + 2.707712349983525454881109975059321670689605166938197378763992255714444407154902012702,  # noqa: E501
            2.324710524099773982415355918398765796109060233222962411944060046314465391054716027841  # noqa: E501
            - 1.866628418170587035753719399566211498666255505244122593996591602841258328965767580089,  # noqa: E501
            -1 / 66,
        ]
    ),
    c=np.array(
        [
            161 / 1000,
            327 / 1000,
            9 / 10,
            0.9800255409045096857298102862870245954942137979563024768854764293221195950761080302604,  # noqa: E501
            1.0,
            1.0,
        ]
    ),
)


class _Tsit5Interpolation(AbstractLocalInterpolation):
    t0: RealScalarLike
    t1: RealScalarLike
    y0: Y
    k: PyTree[Shaped[Array, "7 ?*y"], "Y"]

    def __init__(self, *, t0, t1, y0, y1, k):
        del y1  # exists for API compatibility
        self.t0 = t0
        self.t1 = t1
        self.y0 = y0
        self.k = k

    def evaluate(
        self,
        t0: RealScalarLike,
        t1: Optional[RealScalarLike] = None,
        left: bool = True
    ) -> Y:
        del left
        if t1 is not None:
            return self.evaluate(t1) - self.evaluate(t0)

        t = linear_rescale(self.t0, t0, self.t1)

        # TODO: write as a matrix-multiply or vmap'd polyval
        b1 = (
            -1.0530884977290216
            * t
            * (t - 1.3299890189751412)
            * (t ** 2 - 1.4364028541716351 * t + 0.7139816917074209)
        )
        b2 = 0.1017 * t ** 2 * (t ** 2 - 2.1966568338249754 * t + 1.2949852507374631)
        b3 = (
            2.490627285651252793
            * t ** 2
            * (t ** 2 - 2.38535645472061657 * t + 1.57803468208092486)
        )
        b4 = (
            -16.54810288924490272
            * (t - 1.21712927295533244)
            * (t - 0.61620406037800089)
            * t ** 2
        )
        b5 = (
            47.37952196281928122
            * (t - 1.203071208372362603)
            * (t - 0.658047292653547382)
            * t ** 2
        )
        b6 = -34.87065786149660974 * (t - 1.2) * (t - 0.666666666666666667) * t ** 2
        b7 = 2.5 * (t - 1) * (t - 0.6) * t ** 2
        with jax.numpy_dtype_promotion("standard"):
            return jax.tree.map(
                u.math.add,
                self.y0,
                vector_tree_dot(u.math.stack([b1, b2, b3, b4, b5, b6, b7]), self.k),
                is_leaf=u.math.is_quantity
            )


class Tsit5(AbstractERK):
    r"""Tsitouras' 5/4 method.

    5th order explicit Runge--Kutta method. Has an embedded 4th order method for
    adaptive step sizing. Uses 7 stages with FSAL. Uses 5th order interpolation
    for dense/ts output.

    ??? cite "Reference"

        ```bibtex
        @article{tsitouras2011runge,
          title={Runge--Kutta pairs of order 5 (4) satisfying only the first column
                 simplifying assumption},
          author={Tsitouras, Ch},
          journal={Computers \& Mathematics with Applications},
          volume={62},
          number={2},
          pages={770--775},
          year={2011},
          publisher={Elsevier}
        }
        ```
    """

    tableau: ClassVar[ButcherTableau] = _tsit5_tableau
    interpolation_cls: ClassVar[
        Callable[..., _Tsit5Interpolation]
    ] = _Tsit5Interpolation

    def order(self, terms):
        return 5
