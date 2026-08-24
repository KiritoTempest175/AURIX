#![no_std]
#![no_main]

core::arch::global_asm!(".section .idata\n.global dummy_symbol\ndummy_symbol:\n.long 0");

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    loop {}
}
