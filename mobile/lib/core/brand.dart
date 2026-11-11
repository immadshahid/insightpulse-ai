import 'package:flutter/material.dart';

/// Brand accents on top of [AppPalette]: gradients and per-metric tints.
/// Text never uses these colours; they mark identity (icons, lines, badges).
class Brand {
  const Brand._();

  static const indigo = Color(0xFF4F46E5);
  static const violet = Color(0xFF7C3AED);

  /// Hero gradient (summary card, forecast hero, AI avatar, login header).
  static LinearGradient hero(Brightness b) => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: b == Brightness.light
            ? const [Color(0xFF4F46E5), Color(0xFF7C3AED)]
            : const [Color(0xFF3730A3), Color(0xFF6D28D9)],
      );

  static const _light = {
    'revenue': Color(0xFF4F46E5),
    'orders': Color(0xFF0891B2),
    'avg_order_value': Color(0xFF7C3AED),
    'active_customers': Color(0xFFDB2777),
    'sales': Color(0xFF4F46E5),
    'products': Color(0xFF7C3AED),
    'customers': Color(0xFFDB2777),
    'anomalies': Color(0xFFC2410C),
  };

  /// Same hues stepped lighter for contrast on the dark surface.
  static const _dark = {
    'revenue': Color(0xFF8B85F5),
    'orders': Color(0xFF22D3EE),
    'avg_order_value': Color(0xFFA78BFA),
    'active_customers': Color(0xFFF472B6),
    'sales': Color(0xFF8B85F5),
    'products': Color(0xFFA78BFA),
    'customers': Color(0xFFF472B6),
    'anomalies': Color(0xFFF07A45),
  };

  /// Accent for a KPI key or insight category.
  static Color tint(String key, Brightness b) =>
      (b == Brightness.light ? _light : _dark)[key] ?? (b == Brightness.light ? indigo : _dark['revenue']!);

  static const categoryIcons = {
    'sales': Icons.trending_up_rounded,
    'products': Icons.inventory_2_outlined,
    'customers': Icons.people_alt_outlined,
    'anomalies': Icons.warning_amber_rounded,
  };
}
