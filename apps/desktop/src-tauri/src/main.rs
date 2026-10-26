// Tanpa jendela konsol tambahan di build rilis Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    recap_app_lib::run();
}
