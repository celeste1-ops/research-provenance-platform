"""FSF solver v2 (sample code): the exponent depends on the forcing F."""


def alpha_of(forcing):
    return 1.5 - 0.2 * forcing


def solve(forcing, k=0.8, steps=80, dt=1.0):
    alpha = alpha_of(forcing)
    v, out = 0.0, []
    for n in range(steps + 1):
        out.append((n * dt, v))
        v += dt * k * (1 - v) ** alpha
    return out
