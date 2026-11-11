import 'package:flutter/material.dart';

/// Fades and slides its child in once, after an optional stagger [delay].
/// Skipped when the user has asked the OS to reduce motion.
class FadeSlideIn extends StatelessWidget {
  const FadeSlideIn({super.key, required this.child, this.index = 0});

  final Widget child;

  /// Position in a list; each step adds a short delay (capped).
  final int index;

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.maybeDisableAnimationsOf(context) ?? false) return child;
    final delay = (index.clamp(0, 6)) * 40;
    final total = 260 + delay;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: total),
      curve: Interval(delay / total, 1, curve: Curves.easeOutCubic),
      builder: (context, t, child) => Opacity(
        opacity: t,
        child: Transform.translate(offset: Offset(0, 12 * (1 - t)), child: child),
      ),
      child: child,
    );
  }
}
