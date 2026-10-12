"""FSF solver prototype (sample code): dv/dt = k (1 - v)^alpha, explicit Euler."""


def solve(k=0.8, alpha=1.5, steps=80, dt=1.0):
    v, out = 0.0, []
    for n in range(steps + 1):
        out.append((n * dt, v))
        v += dt * k * (1 - v) ** alpha
    return out
