import 'dart:io';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:mailer/mailer.dart';
import 'package:mailer/smtp_server.dart';
import 'database_helper.dart';

/// An error whose message can be shown to the operator as it is (the Python backend explains what went wrong).
class BackendException implements Exception {
  final String message;
  BackendException(this.message);

  @override
  String toString() => message;
}

class BackendService {
  static const String baseUrl = 'http://127.0.0.1:5000';

  static Future<Map<String, dynamic>> _postJson(
    String path,
    Map<String, dynamic> body, {
    Duration timeout = const Duration(seconds: 60),
  }) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl$path'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(timeout);
      return _handle(response);
    } on BackendException {
      rethrow;
    } catch (e) {
      throw BackendException('Could not communicate with Python backend: $e');
    }
  }

  /// 200 -> the decoded JSON; anything else -> the backend's own error message.
  static Map<String, dynamic> _handle(http.Response response) {
    Map<String, dynamic> data = {};
    try {
      data = Map<String, dynamic>.from(jsonDecode(response.body) as Map);
    } catch (_) {
      // not JSON: keep the empty map
    }
    if (response.statusCode == 200) return data;
    throw BackendException(
        data['error']?.toString() ?? 'Backend error (HTTP ${response.statusCode}).');
  }

  /// CAMERA source: photograph the film on the lightbox. The backend rotates the picture, finds the film,
  /// removes the lightbox and returns {image_path, preview_path, warnings, ...}.
  static Future<Map<String, dynamic>> captureFromCamera({
    required String scanId,
    required String side,
    required String view,
  }) {
    return _postJson('/capture', {'scan_id': scanId, 'side': side, 'view': view});
  }

  /// SOFTCOPY source: turn a file from a USB stick into a PNG (DICOM -> PNG, PNG stays a PNG, anything else -> PNG).
  static Future<Map<String, dynamic>> importSoftcopy({
    required String scanId,
    required String side,
    required String view,
    required String sourcePath,
  }) {
    return _postJson(
      '/import',
      {'scan_id': scanId, 'side': side, 'view': view, 'source_path': sourcePath},
      timeout: const Duration(minutes: 2),
    );
  }

  /// The softcopy files the operator can pick, newest first: the images on a plugged-in USB stick (and in the
  /// backend's inbox folder). Returns {'files': List<Map>, 'volumes': List<String>}; 'volumes' holds the names of
  /// the USB sticks that are connected right now.
  static Future<Map<String, dynamic>> listSoftcopy() async {
    try {
      final response =
          await http.get(Uri.parse('$baseUrl/inbox')).timeout(const Duration(seconds: 30));
      final data = _handle(response);
      final files = ((data['files'] as List?) ?? const [])
          .map((f) => Map<String, dynamic>.from(f as Map))
          .toList();
      final volumes = ((data['volumes'] as List?) ?? const []).map((v) => v.toString()).toList();
      return {'files': files, 'volumes': volumes};
    } on BackendException {
      rethrow;
    } catch (e) {
      throw BackendException('Could not communicate with Python backend: $e');
    }
  }

  /// Runs the AI on the captured views (1 to 4). Returns
  /// {'left': Map?, 'right': Map?, 'combined': Map?, 'note': String, 'mock': bool}.
  static Future<Map<String, dynamic>> analyze({
    required String scanId,
    required List<Map<String, String>> views,
  }) async {
    final data = await _postJson(
      '/analyze',
      {'scan_id': scanId, 'views': views},
      // The 15-network ensemble runs on the Pi's CPU; one analysis can take several minutes.
      timeout: const Duration(minutes: 30),
    );
    final results = (data['results'] as Map?) ?? const {};
    return {
      'left': _stringMapOrNull(results['Left']),
      'right': _stringMapOrNull(results['Right']),
      'combined': _stringMapOrNull(data['combined']),
      'note': (data['note'] ?? '').toString(),
      'mock': data['mock'] == true,
    };
  }

  static Map<String, String>? _stringMapOrNull(dynamic value) {
    if (value is! Map) return null;
    return value.map((k, v) => MapEntry(k.toString(), v.toString()));
  }

  static Future<bool> saveScanRecord({
    required String scanId,
    required List<Map<String, dynamic>> scanData,
    required Map<String, String>? leftResult,
    required Map<String, String>? rightResult,
    required Map<String, String>? combinedResult,
    required bool isAccurate,
  }) async {
    await DatabaseHelper.instance.saveCompleteScan(
      scanId: scanId,
      physicianName: 'Attending',
      // 'N/A' = that breast was not available (no view of it was captured)
      leftClassification: leftResult?['classification'] ?? 'N/A',
      rightClassification: rightResult?['classification'] ?? 'N/A',
      combinedClassification: combinedResult?['classification'] ?? 'Unknown',
      isAccurate: isAccurate,
      scanData: scanData,
    );
    return true;
  }

  static Future<bool> sendEmailReport({
    required String emailAddress,
    required String pdfFilePath,
    required String scanId,
  }) async {
    String senderEmail = 'barbeyto.mikkoloeiroc06@gmail.com'; 
    String appPassword = 'nsme qpzy pmyq lkhy'; 

    final smtpServer = gmail(senderEmail, appPassword);

    final message = Message()
      ..from = Address(senderEmail, 'ATLAS-BC Edge System')
      ..recipients.add(emailAddress)
      ..subject = 'ATLAS-BC Mammography Report: $scanId'
      ..text = 'Please find the attached bilateral mammography AI analysis report for scan $scanId.\n\nThis is an automated message generated by the ATLAS-BC System.'
      ..attachments.add(FileAttachment(File(pdfFilePath)));

    try {
      await send(message, smtpServer);
      return true;
    } catch (e) {
      throw Exception('Failed to send email. Check internet or App Password.');
    }
  }
}
