import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Brand colours and semantic tokens. Text never uses series colours.
@immutable
class AppPalette extends ThemeExtension<AppPalette> {
  const AppPalette({
    required this.background,
    required this.card,
    required this.border,
    required this.text,
    required this.muted,
    required this.accent,
    required this.accentSoft,
    required this.positive,
    required this.negative,
    required this.forecast,
    required this.warningSurface,
  });

  final Color background;
  final Color card;
  final Color border;
  final Color text;
  final Color muted;
  final Color accent;
  final Color accentSoft;
  final Color positive;
  final Color negative;
  final Color forecast;
  final Color warningSurface;

  static const light = AppPalette(
    background: Color(0xFFF6F6FA),
    card: Color(0xFFFFFFFF),
    border: Color(0xFFE6E6EF),
    text: Color(0xFF14142B),
    muted: Color(0xFF5B5B76),
    accent: Color(0xFF4F46E5),
    accentSoft: Color(0xFFEEEDFC),
    positive: Color(0xFF0F7B4F),
    negative: Color(0xFFC2410C),
    forecast: Color(0xFFB45309),
    warningSurface: Color(0xFFFFF4ED),
  );

  /// Dark steps of the same palette, chosen for contrast on the dark surface
  /// (the card colour matches the dark chart background).
  static const dark = AppPalette(
    background: Color(0xFF0E0E1C),
    card: Color(0xFF17172B),
    border: Color(0xFF2C2C46),
    text: Color(0xFFF2F2F8),
    muted: Color(0xFFA6A6C0),
    accent: Color(0xFF8B85F5),
    accentSoft: Color(0xFF26264A),
    positive: Color(0xFF3DBE8A),
    negative: Color(0xFFF07A45),
    forecast: Color(0xFFF0A14A),
    warningSurface: Color(0xFF2E1D14),
  );

  @override
  AppPalette copyWith() => this;

  @override
  AppPalette lerp(ThemeExtension<AppPalette>? other, double t) =>
      t < 0.5 ? this : (other as AppPalette? ?? this);
}

extension PaletteContext on BuildContext {
  AppPalette get palette => Theme.of(this).extension<AppPalette>()!;
}

const double kRadius = 18;
const double kMinTouch = 48;

/// Builds the light or dark theme. [googleFonts] is off in tests (no network).
ThemeData buildTheme(Brightness brightness, {bool googleFonts = true}) {
  final p = brightness == Brightness.light ? AppPalette.light : AppPalette.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: AppPalette.light.accent,
    brightness: brightness,
  ).copyWith(
    primary: p.accent,
    onPrimary: brightness == Brightness.light ? Colors.white : const Color(0xFF14142B),
    surface: p.card,
    onSurface: p.text,
    onSurfaceVariant: p.muted,
    outline: p.border,
    outlineVariant: p.border,
    error: p.negative,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: brightness);
  // Only the family name is taken from google_fonts (it downloads and caches the font);
  // its TextTheme helpers target the separate material_ui package.
  final family = googleFonts ? GoogleFonts.plusJakartaSans().fontFamily : null;
  final textTheme = base.textTheme.apply(fontFamily: family, bodyColor: p.text, displayColor: p.text);
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(14));

  return base.copyWith(
    scaffoldBackgroundColor: p.background,
    textTheme: textTheme,
    extensions: [p],
    appBarTheme: AppBarTheme(
      backgroundColor: p.background,
      foregroundColor: p.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: textTheme.titleLarge?.copyWith(fontSize: 22, fontWeight: FontWeight.w800),
    ),
    cardTheme: CardThemeData(
      color: p.card,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadius),
        side: BorderSide(color: p.border),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(kMinTouch, kMinTouch),
        shape: shape,
        textStyle: textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(kMinTouch, kMinTouch),
        shape: shape,
        side: BorderSide(color: p.border),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.card,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.accent, width: 1.5),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: p.card,
      selectedColor: p.accentSoft,
      side: BorderSide(color: p.border),
      labelStyle: textTheme.labelLarge?.copyWith(color: p.text),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: p.card,
      indicatorColor: p.accentSoft,
      surfaceTintColor: Colors.transparent,
      height: 66,
      elevation: 0,
      labelTextStyle: WidgetStatePropertyAll(
        textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w600),
      ),
    ),
    dividerTheme: DividerThemeData(color: p.border, thickness: 1),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    sliderTheme: base.sliderTheme.copyWith(
      activeTrackColor: p.accent,
      thumbColor: p.accent,
      inactiveTrackColor: p.accentSoft,
    ),
  );
}
