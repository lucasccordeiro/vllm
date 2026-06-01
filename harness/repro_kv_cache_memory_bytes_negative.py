# SPDX-License-Identifier: Apache-2.0
# Behavioral reproduction for Finding #9
# (`--kv-cache-memory-bytes <negative>`), runnable on plain CPython with
# NO vLLM/torch dependency.
#
# The full VllmConfig/Scheduler import-based reproduction (Finding #8's
# style) needs `torch` installed; it is unavailable in this sandbox. The
# defect, however, is pure-Python truthiness + integer logic, so this
# script reproduces it verbatim against the exact upstream expressions.
# Every line is quoted from pinned vllm-project/vllm @ 4438b6e7d (and
# re-confirmed against a local checkout):
#
#   * gpu_worker.py:370  `if kv_cache_memory_bytes := <field>:`  (walrus)
#   * gpu_worker.py:388  `return kv_cache_memory_bytes`
#   * kv_cache_utils.py:935,951  `num_blocks = int(... // ... // ...)`
#                                `num_blocks = max(num_blocks, 0)`
#   * block_pool.py:157  `assert isinstance(num_gpu_blocks, int) and
#                          num_gpu_blocks > 0`
#
# Run: `python3 repro_kv_cache_memory_bytes_negative.py`


def determine_available_memory(kv_cache_memory_bytes, profiled_memory):
    """Verbatim shape of GPUWorker.determine_available_memory's head
    (gpu_worker.py:370-388). The `:=` walrus is a TRUTHINESS test, so a
    negative value (truthy) is returned as-is instead of profiling."""
    if kv_cache_memory_bytes := kv_cache_memory_bytes:  # gpu_worker.py:370
        return kv_cache_memory_bytes                    # gpu_worker.py:388
    return profiled_memory                              # (profiling branch)


def get_num_blocks(available_memory, page_size, num_layers):
    """Verbatim from kv_cache_utils.py:935-951 (no-override path)."""
    num_blocks = int(available_memory // page_size // num_layers)
    num_blocks = max(num_blocks, 0)                     # kv_cache_utils.py:951
    return num_blocks


def block_pool_init(num_gpu_blocks):
    """BlockPool.__init__ invariant, block_pool.py:157."""
    assert isinstance(num_gpu_blocks, int) and num_gpu_blocks > 0


def main():
    # Engine-realistic divisors; profiling would yield a positive budget.
    page_size, num_layers, profiled = 16384, 32, 8 << 30

    print("field=None  (profiling path):")
    avail = determine_available_memory(None, profiled)
    nb = get_num_blocks(avail, page_size, num_layers)
    print(f"   available={avail}  num_blocks={nb}  -> BlockPool OK")
    block_pool_init(nb)

    print("field=0     (falsy -> profiling path):")
    avail = determine_available_memory(0, profiled)
    nb = get_num_blocks(avail, page_size, num_layers)
    print(f"   available={avail}  num_blocks={nb}  -> BlockPool OK")
    block_pool_init(nb)

    print("field=-1    (CLI: --kv-cache-memory-bytes -1):")
    avail = determine_available_memory(-1, profiled)
    nb = get_num_blocks(avail, page_size, num_layers)
    print(f"   available={avail}  num_blocks={nb}  (negative is truthy "
          f"-> returned verbatim; clamp(-1,0)=0)")
    try:
        block_pool_init(nb)
        print("   BlockPool OK (unexpected)")
    except AssertionError:
        print("   -> BlockPool.__init__ assert num_gpu_blocks > 0 FAILS "
              "(bare AssertionError, #43842 crash site)")


if __name__ == "__main__":
    main()
