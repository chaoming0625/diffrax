import functools as ft
import operator

import diffrax
import jax
import jax.numpy as jnp
import jax.random as jrandom
import pytest

from helpers import all_ode_solvers, tree_allclose


@pytest.mark.parametrize("mode", ["linear", "linear2", "cubic"])
def test_interpolation_coeffs(mode):
    # Data is linear so both linear and cubic interpolation should produce the same
    # results where there is missing data.
    ts = ys = jnp.linspace(0.0, 9.0, 10)
    nan_ys = ys.at[jnp.array([0, 3, 4, 6, 9])].set(jnp.nan)
    nan_ys = nan_ys[:, None]

    def _interp(tree, duplicate, **kwargs):
        if duplicate:
            to_interp = jnp.repeat(nan_ys, 2, axis=-1)
        else:
            to_interp = nan_ys
        if tree:
            to_interp = (to_interp,)
        if mode == "linear":
            return diffrax.linear_interpolation(ts, to_interp, **kwargs)

        if mode == "linear2":
            coeffs = diffrax.linear_interpolation(ts, to_interp, **kwargs)
            interp = diffrax.LinearInterpolation(ts, coeffs)
        elif mode == "cubic":
            coeffs = diffrax.backward_hermite_coefficients(ts, to_interp, **kwargs)
            interp = diffrax.CubicInterpolation(ts, coeffs)
        else:
            raise ValueError

        left = jax.vmap(interp.evaluate)(ts)
        right = jax.vmap(ft.partial(interp.evaluate, left=False))(ts)

        def _merge(lef, rig):
            # Must be identical where neither of them are nan
            isnan = jnp.isnan(lef) | jnp.isnan(rig)
            _lef = jnp.where(isnan, 0, lef)
            _rig = jnp.where(isnan, 0, rig)
            assert jnp.array_equal(_lef, _rig)
            return jnp.where(jnp.isnan(rig), lef, rig)

        return jax.tree_map(_merge, left, right)

    interp_ys = _interp(tree=False, duplicate=False)
    true_ys = ys.at[jnp.array([0, 9])].set(jnp.nan)[:, None]
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)
    interp_ys = _interp(tree=False, duplicate=True)
    assert jnp.allclose(interp_ys, jnp.repeat(true_ys, 2, axis=-1), equal_nan=True)
    (interp_ys,) = _interp(tree=True, duplicate=False)
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)

    interp_ys = _interp(tree=False, duplicate=False, fill_forward_nans_at_end=True)
    true_ys = ys.at[0].set(jnp.nan).at[9].set(8.0)[:, None]
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)
    interp_ys = _interp(tree=False, duplicate=True, fill_forward_nans_at_end=True)
    assert jnp.allclose(interp_ys, jnp.repeat(true_ys, 2, axis=-1), equal_nan=True)
    (interp_ys,) = _interp(tree=True, duplicate=False, fill_forward_nans_at_end=True)
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)

    interp_ys = _interp(tree=False, duplicate=False, replace_nans_at_start=5.5)
    true_ys = ys.at[0].set(5.5).at[9].set(jnp.nan)[:, None]
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)
    interp_ys = _interp(tree=False, duplicate=True, replace_nans_at_start=5.5)
    assert jnp.allclose(interp_ys, jnp.repeat(true_ys, 2, axis=-1), equal_nan=True)
    (interp_ys,) = _interp(tree=True, duplicate=False, replace_nans_at_start=(5.5,))
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)


def test_rectilinear_interpolation_coeffs():
    ts = jnp.linspace(0.0, 9.0, 10)
    ys = jnp.array(
        [jnp.nan, 0.2, 0.1, jnp.nan, jnp.nan, 0.5, jnp.nan, 0.8, 0.1, jnp.nan]
    )[:, None]

    interp_ys = diffrax.rectilinear_interpolation(ts, ys)
    true_ys = jnp.array(
        [
            [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9],
            [
                jnp.nan,
                jnp.nan,
                0.2,
                0.2,
                0.1,
                0.1,
                0.1,
                0.1,
                0.1,
                0.1,
                0.5,
                0.5,
                0.5,
                0.5,
                0.8,
                0.8,
                0.1,
                0.1,
                0.1,
            ],
        ]
    ).T
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)
    (interp_ys,) = diffrax.rectilinear_interpolation(ts, (ys,))
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)

    interp_ys = diffrax.rectilinear_interpolation(ts, ys, replace_nans_at_start=5.5)
    true_ys = jnp.array(
        [
            [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9],
            [
                5.5,
                5.5,
                0.2,
                0.2,
                0.1,
                0.1,
                0.1,
                0.1,
                0.1,
                0.1,
                0.5,
                0.5,
                0.5,
                0.5,
                0.8,
                0.8,
                0.1,
                0.1,
                0.1,
            ],
        ]
    ).T
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)
    (interp_ys,) = diffrax.rectilinear_interpolation(
        ts, (ys,), replace_nans_at_start=(5.5,)
    )
    assert jnp.allclose(interp_ys, true_ys, equal_nan=True)


def test_cubic_interpolation_no_deriv0():
    ts = jnp.array([-0.5, 0, 1.0])
    ys = jnp.array([[0.1], [0.5], [-0.2]])
    coeffs = diffrax.backward_hermite_coefficients(ts, ys)
    interp = diffrax.CubicInterpolation(ts, coeffs)

    # First piece is linear

    points = jnp.linspace(-0.5, 0, 10)

    interp_ys = jax.vmap(interp.evaluate)(points)
    true_ys = 0.1 + 0.4 * jnp.linspace(0, 1, 10)[:, None]
    assert jnp.allclose(interp_ys, true_ys)

    derivs = jax.vmap(interp.derivative)(points)
    true_derivs = 0.8
    assert jnp.allclose(derivs, true_derivs)

    # Second piece is cubic

    points = jnp.linspace(0, 1.0, 10)

    interp_ys = jax.vmap(interp.evaluate)(points)
    true_ys = jax.vmap(lambda p: jnp.polyval(jnp.array([1.5, -3, 0.8, 0.5]), p))(
        points
    )[:, None]
    assert jnp.allclose(interp_ys, true_ys)

    derivs = jax.vmap(interp.derivative)(points)
    true_derivs = jax.vmap(lambda p: jnp.polyval(jnp.array([4.5, -6, 0.8]), p))(points)[
        :, None
    ]
    assert jnp.allclose(derivs, true_derivs)


def test_cubic_interpolation_deriv0():
    ts = jnp.array([-0.5, 0, 1.0])
    ys = jnp.array([[0.1], [0.5], [-0.2]])
    coeffs = diffrax.backward_hermite_coefficients(ts, ys, deriv0=jnp.array([0.4]))
    interp = diffrax.CubicInterpolation(ts, coeffs)

    # First piece is cubic

    points = jnp.linspace(-0.5, 0, 10)

    interp_ys = jax.vmap(interp.evaluate)(points)
    true_ys = jax.vmap(lambda p: jnp.polyval(jnp.array([-1.6, -0.8, 0.8, 0.5]), p))(
        points
    )[:, None]
    assert jnp.allclose(interp_ys, true_ys)

    derivs = jax.vmap(interp.derivative)(points)
    true_derivs = jax.vmap(lambda p: jnp.polyval(jnp.array([-4.8, -1.6, 0.8]), p))(
        points
    )[:, None]
    assert jnp.allclose(derivs, true_derivs)

    # Second piece is cubic

    points = jnp.linspace(0, 1.0, 10)

    interp_ys = jax.vmap(interp.evaluate)(points)
    true_ys = jax.vmap(lambda p: jnp.polyval(jnp.array([1.5, -3, 0.8, 0.5]), p))(
        points
    )[:, None]
    assert jnp.allclose(interp_ys, true_ys)

    derivs = jax.vmap(interp.derivative)(points)
    true_derivs = jax.vmap(lambda p: jnp.polyval(jnp.array([4.5, -6, 0.8]), p))(points)[
        :, None
    ]
    assert jnp.allclose(derivs, true_derivs)


@pytest.mark.parametrize("mode", ["linear", "cubic"])
def test_interpolation_classes(mode, getkey):
    length = 8
    num_channels = 3
    ts_ = [
        jnp.linspace(0, 10, length),
        jnp.array([0.0, 2.0, 3.0, 3.1, 4.0, 4.1, 5.0, 5.1]),
    ]
    _make = lambda: jrandom.normal(getkey(), (length, num_channels))
    ys_ = [
        _make(),
        [_make(), {"a": _make(), "b": _make()}],
    ]
    for ts in ts_:
        assert len(ts) == length
        for ys in ys_:
            if mode == "linear":
                interp = diffrax.LinearInterpolation(ts, ys)
            elif mode == "cubic":
                coeffs = diffrax.backward_hermite_coefficients(ts, ys)
                interp = diffrax.CubicInterpolation(ts, coeffs)
            else:
                raise RuntimeError

            assert jnp.array_equal(interp.t0, ts[0])
            assert jnp.array_equal(interp.t1, ts[-1])
            pred_ys = jax.vmap(interp.evaluate)(ts)
            assert tree_allclose(pred_ys, ys)

            if mode == "linear":
                for i, (t0, t1) in enumerate(zip(ts[:-1], ts[1:])):
                    if t0 == t1:
                        continue
                    y0 = jax.tree_map(operator.itemgetter(i), ys)
                    y1 = jax.tree_map(operator.itemgetter(i + 1), ys)
                    points = jnp.linspace(t0, t1, 10)
                    firstval = interp.evaluate(t0, left=False)
                    vals = jax.vmap(interp.evaluate)(points[1:])

                    def _test(firstval, vals, y0, y1):
                        vals = jnp.concatenate([firstval[None], vals])
                        true_vals = y0 + ((points - t0) / (t1 - t0))[:, None] * (
                            y1 - y0
                        )
                        assert jnp.allclose(vals, true_vals)

                    jax.tree_map(_test, firstval, vals, y0, y1)
                    firstderiv = interp.derivative(t0, left=False)
                    derivs = jax.vmap(interp.derivative)(points[1:])

                    def _test(firstderiv, derivs, y0, y1):
                        derivs = jnp.concatenate([firstderiv[None], derivs])
                        true_derivs = (y1 - y0) / (t1 - t0)
                        assert jnp.allclose(derivs, true_derivs)

                    jax.tree_map(_test, firstderiv, derivs, y0, y1)


def _test_dense_interpolation(solver_ctr, getkey, t1):
    y0 = jrandom.uniform(getkey(), (), minval=0.4, maxval=2)
    solver = solver_ctr(lambda t, y, args: -y)
    sol = diffrax.diffeqsolve(
        solver, t0=0, t1=t1, y0=y0, dt0=0.01, saveat=diffrax.SaveAt(dense=True)
    )
    points = jnp.linspace(0, t1, 1000)  # finer resolution than the step size
    vals = jax.vmap(sol.evaluate)(points)
    true_vals = jnp.exp(-points) * y0

    # Tsit5 derivative is not yet implemented.
    if solver_ctr is diffrax.tsit5:
        derivs = None
        true_derivs = None
    else:
        derivs = jax.vmap(sol.derivative)(points)
        true_derivs = -true_vals

    # TODO: apply more stringent tolerances where possible.
    # Need to upgrade away from some of the simplistic interpolation routines used at
    # the moment though.
    tol = 1e-1
    return vals, true_vals, derivs, true_derivs, tol


@pytest.mark.parametrize("solver_ctr", all_ode_solvers)
def test_dense_interpolation(solver_ctr, getkey):
    vals, true_vals, derivs, true_derivs, tol = _test_dense_interpolation(
        solver_ctr, getkey, 1
    )
    assert jnp.allclose(vals, true_vals, atol=tol, rtol=tol)
    if derivs is not None:
        assert jnp.allclose(derivs, true_derivs, atol=tol, rtol=tol)


# When vmap'ing then it can happen that some batch elements take more steps to solve
# than others. This means some padding is used to make things line up; here we test
# that all of this works as intended.
@pytest.mark.parametrize("solver_ctr", all_ode_solvers)
def test_dense_interpolation_vmap(solver_ctr, getkey):
    _test_dense = ft.partial(_test_dense_interpolation, solver_ctr, getkey)
    _test_dense_vmap = jax.vmap(_test_dense, out_axes=(0, 0, 0, 0, None))
    vals, true_vals, derivs, true_derivs, tol = _test_dense_vmap(jnp.array([0.5, 1.0]))
    assert jnp.allclose(vals, true_vals, atol=tol, rtol=tol)
    if derivs is not None:
        assert jnp.allclose(derivs, true_derivs, atol=tol, rtol=tol)