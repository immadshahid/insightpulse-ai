import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';

import 'config.dart';

/// A problem the user should see, in plain words.
class GoogleAuthException implements Exception {
  GoogleAuthException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// "Continue with Google": picks a Google account and returns a Firebase ID token that
/// the server verifies before signing the user in.
abstract class GoogleAuth {
  /// False when the app was built without Firebase settings; the button is then hidden.
  bool get available;

  /// The Firebase ID token for the chosen account, or null if the user backed out.
  Future<String?> signIn();

  /// Forget the Google account so the chooser appears next time.
  Future<void> signOut();
}

class GoogleAuthUnavailable implements GoogleAuth {
  const GoogleAuthUnavailable();

  @override
  bool get available => false;

  @override
  Future<String?> signIn() async => throw GoogleAuthException('Google sign-in is not set up.');

  @override
  Future<void> signOut() async {}
}

class FirebaseGoogleAuth implements GoogleAuth {
  FirebaseGoogleAuth._();

  /// Sets up Firebase and Google sign-in, or returns [GoogleAuthUnavailable] if the app
  /// has no Firebase settings or setup fails (email sign-in keeps working).
  static Future<GoogleAuth> create() async {
    if (!AppConfig.googleSignInConfigured) return const GoogleAuthUnavailable();
    try {
      await Firebase.initializeApp(
        options: const FirebaseOptions(
          apiKey: AppConfig.firebaseApiKey,
          appId: AppConfig.firebaseAppId,
          messagingSenderId: AppConfig.firebaseSenderId,
          projectId: AppConfig.firebaseProjectId,
        ),
      );
      await GoogleSignIn.instance.initialize(serverClientId: AppConfig.googleWebClientId);
      return FirebaseGoogleAuth._();
    } catch (e) {
      debugPrint('Google sign-in unavailable: $e');
      return const GoogleAuthUnavailable();
    }
  }

  @override
  bool get available => true;

  @override
  Future<String?> signIn() async {
    if (!GoogleSignIn.instance.supportsAuthenticate()) {
      throw GoogleAuthException("Google sign-in isn't supported on this device.");
    }
    final GoogleSignInAccount account;
    try {
      account = await GoogleSignIn.instance.authenticate();
    } on GoogleSignInException catch (e) {
      if (e.code == GoogleSignInExceptionCode.canceled || e.code == GoogleSignInExceptionCode.interrupted) {
        return null;
      }
      throw GoogleAuthException(_message(e.code));
    }
    final idToken = account.authentication.idToken;
    if (idToken == null) throw GoogleAuthException('Google did not return a sign-in token.');
    try {
      final result = await FirebaseAuth.instance.signInWithCredential(GoogleAuthProvider.credential(idToken: idToken));
      final token = await result.user?.getIdToken();
      if (token == null) throw GoogleAuthException('Google sign-in did not finish. Try again.');
      return token;
    } on FirebaseAuthException catch (e) {
      throw GoogleAuthException(e.message ?? 'Google sign-in did not finish. Try again.');
    }
  }

  @override
  Future<void> signOut() async {
    await GoogleSignIn.instance.signOut();
    await FirebaseAuth.instance.signOut();
  }

  static String _message(GoogleSignInExceptionCode code) => switch (code) {
    GoogleSignInExceptionCode.uiUnavailable => 'Google sign-in could not open. Try again.',
    GoogleSignInExceptionCode.clientConfigurationError ||
    GoogleSignInExceptionCode.providerConfigurationError => "Google sign-in isn't set up correctly for this app yet.",
    _ => 'Google sign-in did not work. Try again or use your email.',
  };
}
