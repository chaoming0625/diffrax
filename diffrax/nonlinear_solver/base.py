import abc
from typing import Optional, Tuple, TypeVar

import equinox as eqx
import jax
import jax.numpy as jnp
import jax.scipy as jsp

from ..custom_types import PyTree
from ..misc import is_perturbed, ravel_pytree
from ..solution import RESULTS


LU_Jacobian = TypeVar("LU_Jacobian")


class AbstractNonlinearSolver(eqx.Module):
    """Abstract base class for all nonlinear root-finding algorithms.

    Subclasses will be differentiable via the implicit function theorem.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Note that this breaks the descriptor protocol so we have to pass self
        # manually.
        cls._solve = jax.custom_jvp(cls._solve, nondiff_argnums=(0, 1, 2, 3, 4))
        cls._solve.defjvp(_root_solve_jvp)

    @abc.abstractmethod
    def _solve(
        self,
        fn: callable,
        x: PyTree,
        jac: Optional[LU_Jacobian],
        nondiff_args: PyTree,
        diff_args: PyTree,
    ) -> Tuple[PyTree, RESULTS]:
        pass

    def __call__(
        self, fn: callable, x: PyTree, args: PyTree, jac: Optional[LU_Jacobian] = None
    ) -> Tuple[PyTree, RESULTS]:
        """Find `z` such that `fn(z, args) = 0`.

        Arguments:
            fn (callable): The function to find the root of.
            x (PyTree): An initial guess for the location of the root.
            args (PyTree): Arbitrary PyTree parameterising `fn`.
            jac (optional): As returned by self.jac(...). Many root finding algorithms
                use the Jacobian df/dx as part of their iteration. Often they will
                recompute a Jacobian at every step (for example this is done in the
                "standard" Newton solver). In practice computing the Jacobian may be
                expensive, and it may be enough to use a single value for the Jacobian
                held constant throughout the iteration. For the former behaviour, do
                not pass `jac`. To get the latter behaviour, do pass `jac`.

        Gradients will be computed with respect to `args`. (And in particular not with
        respect to either `fn` or `x` -- the latter has zero derivative by definition
        anyway.)

        Returns:
            A 2-tuple `(z, result)`, where `z` (hopefully) solves `fn(z, args) = 0`,
            and `result` is a status code indicating whether the solver managed to
            converge or not.
        """
        diff_args, nondiff_args = eqx.partition(args, is_perturbed)
        return self._solve(self, fn, x, jac, nondiff_args, diff_args)

    @staticmethod
    def jac(fn: callable, x: PyTree, args: PyTree) -> LU_Jacobian:
        flat, unflatten = ravel_pytree(x)
        curried = lambda z: ravel_pytree(fn(unflatten(z), args))[0]
        if not jnp.issubdtype(flat, jnp.inexact):
            # Handle integer arguments
            flat = flat.astype(jnp.float32)
        return jsp.linalg.lu_factor(jax.jacfwd(curried)(flat))


# TODO: I think the jacfwd and the jvp can probably be combined, as they both
# basically do the same thing. That might improve efficiency via parallelism.
# TODO: support differentiating wrt `fn`? This isn't terribly hard -- just pass it as
# part of `diff_args` and use a custom "apply" instead of `fn`. However I can see that
# stating "differentiating wrt `fn` is allowed" might result in confusion if an attempt
# is made to differentiate wrt anything `fn` closes over. (Which is the behaviour of
# `lax.custom_root`. Such closure-differentiation is "magical" behaviour that I won't
# ever put into code I write; if differentiating wrt "closed over values" is expected
# then it's much safer to require that `fn` be a PyTree a la Equinox, but at time of
# writing that isn't yet culturally widespread enough.)
def _root_solve_jvp(
    self: AbstractNonlinearSolver,
    fn: callable,
    x: PyTree,
    jac: Optional[LU_Jacobian],
    nondiff_args: PyTree,
    diff_args: PyTree,
    tang_diff_args: PyTree,
):
    """JVP for differentiably solving for the root of a function, via the implicit
    function theorem.

    Gradients are computed with respect to diff_args.

    This is a lot like lax.custom_root -- we just use less magic. Rather than creating
    gradients for whatever the function happened to close over, we create gradients for
    just diff_args.
    """

    (diff_args,) = diff_args
    (tang_diff_args,) = tang_diff_args
    root, result = self._solve(self, fn, x, jac, nondiff_args, diff_args)

    flat_root, unflatten_root = ravel_pytree(root)
    args = eqx.combine(nondiff_args, diff_args)

    def _for_jac(_root):
        _root = unflatten_root(_root)
        _out = fn(_root, args)
        _out, _ = ravel_pytree(_out)
        return _out

    jac_flat_root = jax.jacfwd(_for_jac)(flat_root)

    flat_diff_args, unflatten_diff_args = ravel_pytree(diff_args)
    flat_tang_diff_args, _ = ravel_pytree(tang_diff_args)

    def _for_jvp(_diff_args):
        _diff_args = unflatten_diff_args(_diff_args)
        _args = eqx.combine(nondiff_args, _diff_args)
        _out = fn(root, _args)
        _out, _ = ravel_pytree(_out)
        return _out

    _, jvp_flat_diff_args = jax.jvp(_for_jvp, (flat_diff_args,), (flat_tang_diff_args,))

    tang_root = -jnp.linalg.solve(jac_flat_root, jvp_flat_diff_args)
    tang_root = unflatten_root(tang_root)
    return (root, result), (tang_root, 0)