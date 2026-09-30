import 'package:flutter/material.dart';
import 'package:flutter_mjpeg/flutter_mjpeg.dart';
import '../services/backend_service.dart';

class CameraPanel extends StatefulWidget {
  final String currentScanId;
  final List<Map<String, dynamic>> scanData;
  final void Function(
    String imagePath,
    String side,
    String view,
    Map<String, String> aiData,
  ) onImageCaptured;
  final VoidCallback onReset;

  /// MJPEG stream served by the Raspberry Pi. Adjust to your backend's URL.
  final String streamUrl;

  const CameraPanel({
    super.key,
    required this.currentScanId,
    required this.scanData,
    required this.onImageCaptured,
    required this.onReset,
    this.streamUrl = 'http://localhost:5000/video_feed',
  });

  @override
  State<CameraPanel> createState() => _CameraPanelState();
}

class _CameraPanelState extends State<CameraPanel> {
  String? _selectedSide;
  String? _selectedView;
  bool _isProcessing = false;

  Future<void> _executeCapture() async {
    if (_selectedSide == null || _selectedView == null) return;
    setState(() => _isProcessing = true);

    try {
      final result = await BackendService.triggerPythonCapture(
        scanId: widget.currentScanId,
        side: _selectedSide!,
        view: _selectedView!,
      );

      final aiData = {
        'classification': result['classification'].toString(),
        'confidence': result['confidence'].toString(),
        'recommendation': result['recommendation'].toString(),
      };

      widget.onImageCaptured(
        result['image_path'].toString(),
        _selectedSide!,
        _selectedView!,
        aiData,
      );
      setState(() {
        _selectedSide = null;
        _selectedView = null;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Failed to connect to AI server',
              style: TextStyle(color: Colors.white),
            ),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isProcessing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Unilateral CC/MLO flow: both captures are the same breast side, so once
    // the first shot is taken, lock the side selector to it and require the
    // other view next instead of letting the side be switched.
    final String? takenSide =
        widget.scanData.isNotEmpty ? widget.scanData[0]['side'] : null;
    final String? takenView =
        widget.scanData.isNotEmpty ? widget.scanData[0]['view'] : null;

    return Column(
      children: [
        // Top Half: Camera Stream
        Expanded(
          flex: 5,
          child: Stack(
            fit: StackFit.expand,
            children: [
              Container(
                color: Colors.black,
                child: Mjpeg(
                  isLive: true,
                  stream: widget.streamUrl,
                  fit: BoxFit.contain,
                  error: (context, error, stack) => const Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.videocam_off,
                            color: Colors.white54, size: 64),
                        SizedBox(height: 16),
                        Text(
                          'Camera stream unavailable',
                          style: TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              if (_selectedSide != null && _selectedView != null)
                Positioned(
                  top: 16,
                  left: 16,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    color: Colors.black54,
                    child: Text(
                      'Target: $_selectedSide Breast ($_selectedView)',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              if (_isProcessing)
                Container(
                  color: Colors.black45,
                  child: const Center(
                    child: CircularProgressIndicator(color: Colors.white),
                  ),
                ),
            ],
          ),
        ),

        // Bottom Half: Controls
        Expanded(
          flex: 5,
          child: Container(
            color: const Color(0xFF0F172A),
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'SCAN CONFIG  (#${widget.scanData.length + 1} of 2)',
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 18,
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: ['Left', 'Right']
                      .map((side) => Expanded(
                            child: Padding(
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 4.0),
                              child: ElevatedButton(
                                style: ElevatedButton.styleFrom(
                                  backgroundColor: _selectedSide == side
                                      ? const Color(0xFF0D9488)
                                      : const Color(0xFF334155),
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 20),
                                ),
                                onPressed: ((takenSide != null &&
                                            takenSide != side) ||
                                        _isProcessing)
                                    ? null
                                    : () =>
                                        setState(() => _selectedSide = side),
                                child: Text(
                                  side,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                            ),
                          ))
                      .toList(),
                ),
                const SizedBox(height: 12),
                Row(
                  children: ['CC', 'MLO']
                      .map((view) => Expanded(
                            child: Padding(
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 4.0),
                              child: ElevatedButton(
                                style: ElevatedButton.styleFrom(
                                  backgroundColor: _selectedView == view
                                      ? const Color(0xFF0D9488)
                                      : const Color(0xFF334155),
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 20),
                                ),
                                onPressed: (takenView == view || _isProcessing)
                                    ? null
                                    : () =>
                                        setState(() => _selectedView = view),
                                child: Text(
                                  view,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                            ),
                          ))
                      .toList(),
                ),
                const Spacer(),
                if (widget.scanData.isNotEmpty)
                  TextButton.icon(
                    icon: const Icon(Icons.refresh, color: Colors.redAccent),
                    label: const Text(
                      'Discard Capture & Reset',
                      style: TextStyle(
                        color: Colors.redAccent,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    onPressed: _isProcessing ? null : widget.onReset,
                  ),
                const SizedBox(height: 8),
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF0D9488),
                    padding: const EdgeInsets.symmetric(vertical: 20),
                  ),
                  onPressed: (_selectedSide != null &&
                          _selectedView != null &&
                          !_isProcessing)
                      ? _executeCapture
                      : null,
                  icon: const Icon(Icons.camera, color: Colors.white, size: 28),
                  label: const Text(
                    'CAPTURE',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}