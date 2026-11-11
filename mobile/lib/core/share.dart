import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

/// Opens the system share sheet with [text]. Overridden in tests.
typedef Sharer = Future<void> Function(String text, {String? subject});

Future<void> _systemShare(String text, {String? subject}) async {
  await SharePlus.instance.share(ShareParams(text: text, subject: subject));
}

final sharerProvider = Provider<Sharer>((ref) => _systemShare);

/// Adds the app signature to shared text.
String withSignature(String text) => '$text\n\n— via InsightPulse AI';
