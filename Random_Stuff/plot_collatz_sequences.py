import matplotlib.pyplot as plt

# ---------------------------
# Core Collatz logic
# ---------------------------
def collatz_sequence(n):
    if n <= 0:
        raise ValueError("n must be positive")
    seq = [n]
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        seq.append(n)
    return seq

def stopping_time(n):
    return len(collatz_sequence(n)) - 1

def max_excursion(n):
    return max(collatz_sequence(n))


# ---------------------------
# MAIN VISUALIZATION
# ---------------------------
if __name__ == "__main__":

    n = 27
    N = 10000
    x = range(1, N + 1)

    seq = collatz_sequence(n)
    stop_times = [stopping_time(i) for i in x]
    max_vals = [max_excursion(i) for i in x]

    # ===== Create ONE window with 3 plots =====
    fig, axs = plt.subplots(
        3, 1,
        figsize=(12, 14),
        constrained_layout=True
    )

    # --- Plot 1: Single trajectory ---
    axs[0].plot(seq, linewidth=1.5)
    axs[0].set_title(f"Collatz trajectory (n = {n})", fontsize=14)
    axs[0].set_xlabel("Step")
    axs[0].set_ylabel("Value")
    axs[0].grid(True,alpha=0.3)

    # --- Plot 2: Stopping time ---
    axs[1].scatter(x, stop_times, s=1)
    axs[1].set_title("Stopping time vs starting number", fontsize=14)
    axs[1].set_xlabel("Starting number")
    axs[1].set_ylabel("Stopping time")
    axs[1].grid(True, alpha=0.3)

    # --- Plot 3: Maximum excursion ---
    axs[2].scatter(x, max_vals, s=1)
    axs[2].set_yscale("log")
    axs[2].set_title("Maximum value reached (log scale)", fontsize=14)
    axs[2].set_xlabel("Starting number")
    axs[2].set_ylabel("Max value")
    axs[2].grid(True, alpha=0.3)

    plt.show()
