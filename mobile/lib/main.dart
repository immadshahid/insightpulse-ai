import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/api_client.dart';
import 'core/google_auth.dart';
import 'core/prefs.dart';
import 'state/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final tokens = SecureTokenStore();
  await tokens.load();
  final prefs = await SharedPrefs.load();
  final google = await FirebaseGoogleAuth.create();
  runApp(
    ProviderScope(
      // Failed calls (e.g. Ask AI not configured) should surface at once, not retry.
      retry: (retryCount, error) => null,
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        prefsProvider.overrideWithValue(prefs),
        googleAuthProvider.overrideWithValue(google),
      ],
      child: const InsightPulseApp(),
    ),
  );
}
